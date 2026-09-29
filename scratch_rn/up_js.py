JS=r"""JSON.stringify([...document.querySelectorAll('article')].map(a=>({t:a.innerText.replace(/\n/g,' | ').slice(0,700),h:(a.querySelector('a[href*="/jobs/"]')||{}).href})))"""
