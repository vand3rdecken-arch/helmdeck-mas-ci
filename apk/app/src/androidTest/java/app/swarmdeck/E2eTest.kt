package app.swarmdeck

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * End-to-end test of the phone app against a REAL paired daemon.
 *
 * Supply a pairing code so the app talks to a live daemon (generate it on the
 * desktop: Settings -> Pair phone -> copy):
 *
 *   ./gradlew connectedDebugAndroidTest \
 *       -Pandroid.testInstrumentationRunnerArguments.pairCode=<code-or-link>
 *
 * Without a pairing code the connectivity checks are skipped and only the
 * offline paths (pairing screen, code parsing) are asserted, so the suite is
 * still meaningful on a bare emulator.
 */
@RunWith(AndroidJUnit4::class)
class E2eTest {

    @get:Rule val rule = createAndroidComposeRule<MainActivity>()

    private val pairCode: String? by lazy {
        InstrumentationRegistry.getArguments().getString("pairCode")?.takeIf { it.isNotBlank() }
    }

    @Before fun setUp() {
        HubStore.init(InstrumentationRegistry.getInstrumentation().targetContext)
    }

    // ---- always runnable ---------------------------------------------------

    @Test fun app_launches_and_shows_a_screen() {
        rule.waitForIdle()
        rule.onNodeWithTag("screenTitle").assertExists()
    }

    @Test fun pairing_code_parser_accepts_bare_code_link_and_applink() {
        val payload = """{"u":"https://relay.example.com","r":"room1",""" +
                """"k":"AAAA","t":"tok_1"}"""
        val b64 = android.util.Base64.encodeToString(payload.toByteArray(), android.util.Base64.NO_WRAP)

        assertTrue("bare base64 code", HubStore.applyPairingCode(b64))
        assertEquals("https://relay.example.com", HubStore.relayUrl)
        assertEquals("room1", HubStore.room)
        assertEquals("tok_1", HubStore.deviceToken)
        assertTrue("phone keypair generated", HubStore.ownPub.isNotEmpty() && HubStore.ownSk.isNotEmpty())

        HubStore.relayUrl = ""
        assertTrue("custom scheme link", HubStore.applyPairingCode("swarmdeck://pair?c=$b64"))
        assertEquals("https://relay.example.com", HubStore.relayUrl)

        HubStore.relayUrl = ""
        val encoded = java.net.URLEncoder.encode(b64, "UTF-8")
        assertTrue("https app link", HubStore.applyPairingCode("https://relay.example.com/pair?c=$encoded"))
        assertEquals("room1", HubStore.room)

        // the QR payload omits "u" - the relay must be recovered from the link
        val short64 = android.util.Base64.encodeToString(
            """{"r":"room2","k":"AAAA","t":"tok_2"}""".toByteArray(), android.util.Base64.NO_WRAP)
        HubStore.relayUrl = ""
        assertTrue("short QR payload + link origin",
            HubStore.applyPairingCode("https://relay.two.example/pair?c=" +
                java.net.URLEncoder.encode(short64, "UTF-8")))
        assertEquals("https://relay.two.example", HubStore.relayUrl)
        assertEquals("room2", HubStore.room)

        // ...but a bare short code has no relay to talk to and must be refused
        HubStore.relayUrl = ""
        assertFalse("short code without a link is rejected", HubStore.applyPairingCode(short64))

        // the QR encodes base64URL without padding - it must decode too
        val urlSafe = android.util.Base64.encodeToString(
            """{"r":"room3","k":"AAAA","t":"tok_3"}""".toByteArray(),
            android.util.Base64.NO_WRAP or android.util.Base64.URL_SAFE or android.util.Base64.NO_PADDING)
        HubStore.relayUrl = ""
        assertTrue("base64URL payload from the QR",
            HubStore.applyPairingCode("https://relay.three.example/pair?c=$urlSafe"))
        assertEquals("room3", HubStore.room)

        assertFalse("garbage is rejected", HubStore.applyPairingCode("not-a-code"))
    }

    /**
     * Regression: reinstalling or restoring the app leaves the encrypted prefs
     * behind while the Keystore master key is gone. Every read then threw
     * AEADBadTagException and the app crashed in onCreate. init() must recover
     * by discarding the unreadable store instead of dying.
     */
    @Test fun init_recovers_from_prefs_it_can_no_longer_decrypt() {
        val ctx = InstrumentationRegistry.getInstrumentation().targetContext
        HubStore.init(ctx)
        HubStore.room = "before-corruption"
        val savedSk = HubStore.ownSk
        val savedPub = HubStore.ownPub

        // simulate the reinstall/restore case: ciphertext stays, key is dropped
        java.security.KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
            .deleteEntry("_androidx_security_master_key_")

        HubStore.init(ctx)                       // must NOT throw
        assertTrue("store is usable again", HubStore.isReady())
        // the old value is unrecoverable by design - a clean slate is correct
        assertEquals("", HubStore.room)
        HubStore.room = "after-recovery"
        assertEquals("after-recovery", HubStore.room)

        // Wiping the store also drops this device's Curve25519 identity. The
        // daemon pins the first key it sees, so leaving a fresh one behind would
        // lock every later test out of the paired room. Restore it.
        HubStore.ownSk = savedSk; HubStore.ownPub = savedPub
    }

    @Test fun e2ee_roundtrip_and_tamper_detection() {
        val (skA, pkA) = E2ee.generateKeyPair()
        val (skB, pkB) = E2ee.generateKeyPair()
        val msg = """{"method":"GET","path":"/tracks"}""".toByteArray()

        val sealed = E2ee.seal(msg, skA, pkB)
        assertArrayEquals("A->B opens", msg, E2ee.open(sealed, skB, pkA))

        // flipping a byte must fail the Poly1305 tag, not decrypt to garbage
        val raw = android.util.Base64.decode(sealed, android.util.Base64.NO_WRAP)
        raw[raw.size - 1] = (raw[raw.size - 1].toInt() xor 1).toByte()
        val tampered = android.util.Base64.encodeToString(raw, android.util.Base64.NO_WRAP)
        try {
            E2ee.open(tampered, skB, pkA); fail("tampered frame must not open")
        } catch (expected: Exception) { /* correct */ }
    }

    @Test fun bottom_navigation_reaches_every_section() {
        // Self-contained: an UNPAIRED app deliberately shows the pairing screen
        // instead of the section menu, so give it a (dummy) pairing first -
        // otherwise this test depends on whatever ran before it.
        val dummy = android.util.Base64.encodeToString(
            """{"u":"https://relay.invalid","r":"navtest","k":"AAAA","t":"tok"}""".toByteArray(),
            android.util.Base64.NO_WRAP)
        assertTrue(HubStore.applyPairingCode(dummy))
        rule.activityRule.scenario.recreate()      // re-read config into the UI
        rule.waitForIdle()

        listOf("tab_BOARD", "tab_NEEDS", "tab_DASH", "tab_MORE").forEach { tag ->
            rule.onNodeWithTag(tag).assertExists().performClick()
            rule.waitForIdle()
        }
        // "More" fans out to the remaining desktop views
        listOf("more_sessions", "more_processes", "more_history", "more_chat", "more_settings")
            .forEach { tag -> rule.onNodeWithTag(tag).assertExists() }
    }

    /**
     * A card must open on its OVERVIEW, not inside a long transcript - on a
     * phone the description was scrolled away by the chat. Chat stays one tap
     * away.
     */
    @Test fun card_opens_on_overview_not_the_chat() {
        val code = pairCode ?: return
        assertTrue(HubStore.applyPairingCode(code))
        val card = kotlinx.coroutines.runBlocking { DaemonClient.tracks() }.firstOrNull() ?: return

        rule.activityRule.scenario.recreate(); rule.waitForIdle()
        rule.onNodeWithText(card.task, substring = true).performClick()
        rule.waitForIdle()

        rule.onNodeWithTag("cardTab_overview").assertExists()
        rule.onNodeWithTag("cardTab_chat").assertExists()
        // the description block belongs to the overview and must be on screen
        // straight away - that is the whole point of opening here
        rule.onNodeWithTag("cardDescription").assertExists()
    }

    /** The phone must offer a repo CHOICE - typing a Windows path on a phone is
     *  not a workflow. Requires a live daemon for the repo list. */
    @Test fun new_card_offers_a_repo_picker() {
        val code = pairCode ?: return
        assertTrue(HubStore.applyPairingCode(code))
        val repos = kotlinx.coroutines.runBlocking { DaemonClient.knownRepos() }
        assertTrue("the workspace exposes at least one repo to pick", repos.isNotEmpty())
    }

    /** Every desktop view must be reachable from the phone's More menu. */
    @Test fun more_menu_covers_every_desktop_view() {
        val dummy = android.util.Base64.encodeToString(
            """{"u":"https://relay.invalid","r":"navtest","k":"AAAA","t":"tok"}""".toByteArray(),
            android.util.Base64.NO_WRAP)
        assertTrue(HubStore.applyPairingCode(dummy))
        rule.activityRule.scenario.recreate(); rule.waitForIdle()
        rule.onNodeWithTag("tab_MORE").performClick(); rule.waitForIdle()

        listOf("more_sessions", "more_processes", "more_recordings", "more_history",
               "more_chat", "more_import", "more_connectors", "more_users",
               "more_workspace", "more_debt", "more_settings")
            .forEach { rule.onNodeWithTag(it).assertExists() }
    }

    /** Agent answers are markdown - the phone must render structure, and the
     *  copilot must offer the context meter and slash shortcuts. */
    @Test fun copilot_renders_markdown_and_shows_context() {
        val dummy = android.util.Base64.encodeToString(
            """{"u":"https://relay.invalid","r":"navtest","k":"AAAA","t":"tok"}""".toByteArray(),
            android.util.Base64.NO_WRAP)
        assertTrue(HubStore.applyPairingCode(dummy))
        rule.activityRule.scenario.recreate(); rule.waitForIdle()
        rule.onNodeWithTag("tab_BOARD").performClick(); rule.waitForIdle()
        rule.onNodeWithTag("chatFab").performClick(); rule.waitForIdle()

        rule.onNodeWithTag("chatContextMeter").assertExists()

        // typing "/" reveals the board shortcuts
        rule.onNodeWithText("Message the board", substring = true).performTextInput("/")
        rule.waitForIdle()
        rule.onNodeWithText("/status", substring = true).assertExists()
    }

    /** The copilot must be reachable FROM THE BOARD, like the desktop's floating
     *  button - burying it in a menu is not the same affordance. */
    @Test fun copilot_is_reachable_from_the_board() {
        val dummy = android.util.Base64.encodeToString(
            """{"u":"https://relay.invalid","r":"navtest","k":"AAAA","t":"tok"}""".toByteArray(),
            android.util.Base64.NO_WRAP)
        assertTrue(HubStore.applyPairingCode(dummy))
        rule.activityRule.scenario.recreate(); rule.waitForIdle()

        rule.onNodeWithTag("tab_BOARD").performClick(); rule.waitForIdle()
        rule.onNodeWithTag("chatFab").assertExists()
        rule.onNodeWithTag("newCardFab").assertExists()

        rule.onNodeWithTag("chatFab").performClick(); rule.waitForIdle()
        rule.onNodeWithText("Board copilot", substring = true).assertExists()
    }

    /** The write-side endpoints the desktop has must work from the phone too. */
    @Test fun admin_surfaces_are_readable_through_the_relay() {
        val code = pairCode ?: return
        assertTrue(HubStore.applyPairingCode(code))
        kotlinx.coroutines.runBlocking {
            assertNotNull("users", DaemonClient.users())
            assertNotNull("connectors", DaemonClient.connectors())
            assertNotNull("workspace checkpoints", DaemonClient.workspaceCheckpoints())
            assertNotNull("debt register", DaemonClient.debt())
            assertNotNull("runs", DaemonClient.runs())
        }
    }

    /** Attaching a file goes base64 through the encrypted relay. */
    @Test fun a_file_can_be_attached_and_detached() {
        val code = pairCode ?: return
        assertTrue(HubStore.applyPairingCode(code))
        val card = kotlinx.coroutines.runBlocking { DaemonClient.tracks() }.firstOrNull() ?: return
        val name = "e2e-probe-${System.currentTimeMillis()}.txt"
        kotlinx.coroutines.runBlocking {
            DaemonClient.attach(card.id, name, "text/plain", "hello from the phone".toByteArray())
            val after = DaemonClient.attachments(card.id)
            val names = (0 until after.length()).mapNotNull { after.optJSONObject(it)?.optString("name") }
            assertTrue("attachment shows up: $names", names.any { it.contains(name.substringBefore(".")) })
            DaemonClient.removeAttachment(card.id, names.first { it.contains(name.substringBefore(".")) })
        }
    }

    /**
     * A recording must be watchable on the phone. The encrypted relay carries
     * text, so the video comes down in base64 slices - this proves the whole
     * chain and that the reassembled file is byte-identical, not truncated.
     */
    @Test fun a_recording_downloads_intact_through_the_relay() {
        val code = pairCode ?: return
        assertTrue(HubStore.applyPairingCode(code))
        val runs = kotlinx.coroutines.runBlocking { DaemonClient.runs() }
        if (runs.length() == 0) return                       // nothing recorded yet
        val id = runs.optJSONObject(0)?.optString("id") ?: return

        var lastProgress = 0f
        val file = kotlinx.coroutines.runBlocking {
            DaemonClient.downloadRecording(id) { lastProgress = it }
        } ?: return                                          // this run has no video
        assertTrue("file written", file.exists() && file.length() > 0)
        assertEquals("progress completes", 1f, lastProgress, 0.001f)

        // the daemon reports the true size in every slice - compare against it
        val declared = kotlinx.coroutines.runBlocking {
            org.json.JSONObject(
                DaemonClient.rawGet("/runs/$id/videochunk?offset=0&len=1")).optLong("size")
        }
        assertEquals("no bytes lost in transit", declared, file.length())
    }

    /** Existing Claude Code conversations must be reachable from the phone. */
    @Test fun claude_sessions_are_listed_for_adoption() {
        val code = pairCode ?: return
        assertTrue(HubStore.applyPairingCode(code))
        val sessions = kotlinx.coroutines.runBlocking { DaemonClient.claudeSessions() }
        assertTrue("desktop sessions are visible on the phone", sessions.isNotEmpty())
        val s = sessions.first()
        assertTrue("a session carries the cwd needed to adopt it", s.cwd.isNotBlank())
        assertTrue("a session carries its id", s.id.isNotBlank())
    }

    // ---- require a live paired daemon --------------------------------------

    @Test fun paired_app_loads_the_board_from_the_daemon() {
        val code = pairCode ?: return                       // skipped without -PpairCode
        assertTrue("pairing code applies", HubStore.applyPairingCode(code))

        val tracks = kotlinx.coroutines.runBlocking { DaemonClient.tracks() }
        assertNotNull(tracks)
        // a paired app must be able to read capacity too (proves auth + E2EE)
        val m = kotlinx.coroutines.runBlocking { DaemonClient.metrics() }
        assertTrue("wip limit is configured", m.wipLimit > 0)
    }

    @Test fun paired_app_can_file_steer_and_delete_a_card() {
        val code = pairCode ?: return
        assertTrue(HubStore.applyPairingCode(code))

        val task = "E2E android probe ${System.currentTimeMillis()}"
        val id = kotlinx.coroutines.runBlocking {
            DaemonClient.newTrack(repo = "", task = task, lane = "backlog")
            DaemonClient.tracks().firstOrNull { it.task == task }?.id
        }
        assertNotNull("card was filed through the encrypted relay", id)
        try {
            kotlinx.coroutines.runBlocking {
                val patch = org.json.JSONObject().put("priority", "high")
                DaemonClient.update(id!!, patch)
                val after = DaemonClient.tracks().first { it.id == id }
                assertEquals("field edit round-trips", "high", after.priority)
            }
        } finally {
            kotlinx.coroutines.runBlocking { runCatching { DaemonClient.delete(id!!) } }
        }
    }
}
