//! Owner-only named pipes (Windows). A pipe created with a NULL security descriptor gets the
//! default DACL, which grants Everyone READ - any local user could listen to frames. Here the
//! DACL names the current user's SID and nobody else, remote clients are refused, and the first
//! instance flag makes a second bridge (or a squatter that got there first) fail loudly.

use std::io::{self, Read, Write};
use std::ptr::null_mut;

use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, LocalFree, ERROR_PIPE_CONNECTED, HANDLE, INVALID_HANDLE_VALUE};
use windows_sys::Win32::Security::Authorization::{ConvertSidToStringSidW, ConvertStringSecurityDescriptorToSecurityDescriptorW, SDDL_REVISION_1};
use windows_sys::Win32::Security::{GetTokenInformation, TokenUser, SECURITY_ATTRIBUTES, TOKEN_QUERY, TOKEN_USER};
use windows_sys::Win32::Storage::FileSystem::{
    FlushFileBuffers, ReadFile, WriteFile, FILE_FLAG_FIRST_PIPE_INSTANCE, PIPE_ACCESS_INBOUND, PIPE_ACCESS_OUTBOUND,
};
use windows_sys::Win32::System::Pipes::{
    ConnectNamedPipe, CreateNamedPipeW, DisconnectNamedPipe, PIPE_READMODE_BYTE, PIPE_REJECT_REMOTE_CLIENTS, PIPE_TYPE_BYTE, PIPE_WAIT,
};
use windows_sys::Win32::System::Threading::{GetCurrentProcess, OpenProcessToken};

fn wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

/// The current user's SID as a string ("S-1-5-21-...").
pub fn current_user_sid() -> io::Result<String> {
    unsafe {
        let mut tok: HANDLE = null_mut();
        if OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut tok) == 0 {
            return Err(io::Error::last_os_error());
        }
        let mut need = 0u32;
        GetTokenInformation(tok, TokenUser, null_mut(), 0, &mut need);
        let mut buf = vec![0u8; need as usize];
        let ok = GetTokenInformation(tok, TokenUser, buf.as_mut_ptr().cast(), need, &mut need);
        CloseHandle(tok);
        if ok == 0 {
            return Err(io::Error::last_os_error());
        }
        let user = &*(buf.as_ptr() as *const TOKEN_USER);
        let mut sid_w: *mut u16 = null_mut();
        if ConvertSidToStringSidW(user.User.Sid, &mut sid_w) == 0 {
            return Err(io::Error::last_os_error());
        }
        let mut len = 0;
        while *sid_w.add(len) != 0 {
            len += 1;
        }
        let s = String::from_utf16_lossy(std::slice::from_raw_parts(sid_w, len));
        LocalFree(sid_w.cast());
        Ok(s)
    }
}

/// The SDDL of every pipe here: protected DACL, one ACE, full access for the given SID.
pub fn sddl_for(sid: &str) -> String {
    format!("D:P(A;;GA;;;{sid})")
}

pub struct Pipe {
    h: HANDLE,
}

// A pipe handle is a kernel object; each Pipe is only ever used by one thread at a time here.
unsafe impl Send for Pipe {}
unsafe impl Sync for Pipe {}

impl Pipe {
    /// Create the single instance of `path`. `inbound` = this side only reads.
    pub fn create(path: &str, inbound: bool) -> io::Result<Pipe> {
        let sddl = wide(&sddl_for(&current_user_sid()?));
        unsafe {
            let mut sd: *mut core::ffi::c_void = null_mut();
            if ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.as_ptr(), SDDL_REVISION_1, &mut sd, null_mut()) == 0 {
                return Err(io::Error::last_os_error());
            }
            let sa = SECURITY_ATTRIBUTES { nLength: size_of::<SECURITY_ATTRIBUTES>() as u32, lpSecurityDescriptor: sd, bInheritHandle: 0 };
            let dir = if inbound { PIPE_ACCESS_INBOUND } else { PIPE_ACCESS_OUTBOUND };
            let h = CreateNamedPipeW(
                wide(path).as_ptr(),
                dir | FILE_FLAG_FIRST_PIPE_INSTANCE,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                1,
                64 * 1024,
                64 * 1024,
                0,
                &sa,
            );
            let err = io::Error::last_os_error();
            LocalFree(sd);
            if h == INVALID_HANDLE_VALUE {
                return Err(err);
            }
            Ok(Pipe { h })
        }
    }

    /// Block until a client connects.
    pub fn connect(&self) -> io::Result<()> {
        unsafe {
            if ConnectNamedPipe(self.h, null_mut()) == 0 && GetLastError() != ERROR_PIPE_CONNECTED {
                return Err(io::Error::last_os_error());
            }
        }
        Ok(())
    }

    /// Drop the current client so the next one can connect.
    pub fn disconnect(&self) {
        unsafe {
            DisconnectNamedPipe(self.h);
        }
    }
}

impl Drop for Pipe {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.h);
        }
    }
}

impl Read for &Pipe {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        let mut n = 0u32;
        let ok = unsafe { ReadFile(self.h, buf.as_mut_ptr().cast(), buf.len().min(u32::MAX as usize) as u32, &mut n, null_mut()) };
        if ok == 0 {
            let e = io::Error::last_os_error();
            // the daemon closed its end: a normal end of stream
            if e.raw_os_error() == Some(109) {
                return Ok(0);
            }
            return Err(e);
        }
        Ok(n as usize)
    }
}

impl Write for &Pipe {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        let mut n = 0u32;
        let ok = unsafe { WriteFile(self.h, buf.as_ptr().cast(), buf.len().min(u32::MAX as usize) as u32, &mut n, null_mut()) };
        if ok == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(n as usize)
    }
    fn flush(&mut self) -> io::Result<()> {
        unsafe {
            if FlushFileBuffers(self.h) == 0 {
                return Err(io::Error::last_os_error());
            }
        }
        Ok(())
    }
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_acl_names_one_sid_and_is_protected() {
        let sid = current_user_sid().unwrap();
        assert!(sid.starts_with("S-1-5-"), "{sid}");
        let s = sddl_for(&sid);
        assert!(s.starts_with("D:P("), "protected DACL: {s}");
        assert_eq!(s.matches("(A;").count(), 1, "exactly one ACE: {s}");
        assert!(!s.contains(";WD)") && !s.contains(";;;WD"), "Everyone must not be in it: {s}");
    }

    #[test]
    fn a_second_instance_of_the_same_name_is_refused() {
        let name = format!("\\\\.\\pipe\\hd-bridge-unit-{}", std::process::id());
        let a = Pipe::create(&name, true).unwrap();
        assert!(Pipe::create(&name, true).is_err(), "FILE_FLAG_FIRST_PIPE_INSTANCE must refuse a squatter");
        drop(a);
    }
}
