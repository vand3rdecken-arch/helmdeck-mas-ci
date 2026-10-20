// Shared shell for the app pages (/readproof/*, /label-doktor/*): language
// option + Google Analytics consent. Same pattern as the main site (index.js):
// English is the default and what renders without JavaScript; the toggle
// switches to German, the choice lives in localStorage under the SAME key
// (hd_lang) so it carries across helmdeck.de.
//
// Markup contract: every text block exists twice, class "en" and class "de".
//   L(en, de)        inline pair   <span class=en>..</span><span class=de>..</span>
//   B(en, de)        block pair    <div class=en lang=en>..</div><div class=de lang=de>..</div>
// CSS shows .en unless <html lang=de>. check_lang_blocks.mjs enforces the pairs.
//
// Analytics: GA4 measurement ID of the existing property "Label Doctor
// Marketplace". Consent Mode v2 defaults are all "denied"; gtag.js is not even
// requested before the visitor clicks Accept. No Google signals, no ad features.

export const GA_ID = "G-8V1ZGSKD54";

export const L = (en, de) => `<span class=en>${en}</span><span class=de>${de}</span>`;
export const B = (en, de) => `<div class=en lang=en>${en}</div>\n<div class=de lang=de>${de}</div>`;

export const LANG_CSS = `.de{display:none}html[lang=de] .en{display:none}html[lang=de] .de{display:revert}
.bar{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}.bar p{margin:0}
.lang{background:#1A1C1D;color:#E4E6E6;border:1px solid #3a3d3f;border-radius:6px;padding:4px 10px;font:600 13px system-ui,sans-serif;cursor:pointer}
.lang:hover{border-color:#6CB2EC}
.foot{font-size:14px}.foot a{color:#959A9D}
#cb{position:fixed;left:0;right:0;bottom:0;background:#15171A;border-top:1px solid #3a3d3f;padding:14px 20px;z-index:10}
#cb[hidden]{display:none}
#cb .in{max-width:720px;margin:0 auto}#cb p{margin:0 0 10px;font-size:14px;line-height:1.5}
#cb .btns{display:flex;gap:10px}
#cb button{flex:1;max-width:200px;background:#1A1C1D;color:#E4E6E6;border:1px solid #6CB2EC;border-radius:6px;padding:9px 14px;font:600 14px system-ui,sans-serif;cursor:pointer}
#cb button:hover{background:#22262a}`;

// Footer link + consent banner. Both buttons share one rule (#cb button): same
// size, same colour. No wall: the page stays readable and usable behind it.
export const foot = (slug) => `<hr>
<p class="muted foot"><a href="#" id=cs>${L("Cookie settings", "Cookie-Einstellungen")}</a></p>
<div id=cb hidden role=dialog aria-label="Cookie settings"><div class=in>
<p>${L(
  `We would like to use Google Analytics to measure how this website is used. It only runs if you accept; until then no data is sent to Google. You can change your choice at any time via &quot;Cookie settings&quot; in the footer. Details: <a href="/${slug}/privacy">privacy page</a>.`,
  `Wir möchten mit Google Analytics messen, wie diese Website genutzt wird. Das läuft nur mit deiner Zustimmung; bis dahin werden keine Daten an Google gesendet. Du kannst deine Wahl jederzeit über „Cookie-Einstellungen“ im Fußbereich ändern. Details: <a href="/${slug}/privacy">Datenschutzseite</a>.`
)}</p>
<div class=btns><button type=button id=cy>${L("Accept", "Akzeptieren")}</button><button type=button id=cn>${L("Decline", "Ablehnen")}</button></div>
</div></div>`;

export const LANG_JS = `(function(){
var ID="${GA_ID}",LK="hd_lang",CK="hd_ga_consent",h=document.documentElement,d=document;
function get(k){try{return localStorage.getItem(k)}catch(e){return null}}
function set(k,v){try{localStorage.setItem(k,v)}catch(e){}}
var lang=get(LK)==="de"?"de":"en";
var m=d.querySelector("meta[name=hd-title-de]"),t0=d.title;
var btn=d.createElement("button");btn.type="button";btn.className="lang";btn.setAttribute("aria-label","Switch language");
function apply(){h.lang=lang;btn.textContent=lang==="de"?"EN":"DE";if(m)d.title=lang==="de"?m.content:t0}
btn.onclick=function(){lang=lang==="de"?"en":"de";set(LK,lang);apply()};
var bar=d.querySelector(".bar");if(bar)bar.appendChild(btn);
apply();
window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments)}
gtag("consent","default",{ad_storage:"denied",ad_user_data:"denied",ad_personalization:"denied",analytics_storage:"denied"});
var loaded=false;
function load(){if(loaded)return;loaded=true;var s=d.createElement("script");s.async=true;s.src="https://www.googletagmanager.com/gtag/js?id="+ID;d.head.appendChild(s);gtag("js",new Date());gtag("config",ID,{allow_google_signals:false,allow_ad_personalization_signals:false})}
function grant(){window["ga-disable-"+ID]=false;gtag("consent","update",{analytics_storage:"granted"});load()}
function wipe(){var hs=[location.hostname,"."+location.hostname,"."+location.hostname.split(".").slice(-2).join(".")];d.cookie.split(";").forEach(function(c){var n=c.split("=")[0].trim();if(n==="_ga"||n.indexOf("_ga_")===0)hs.forEach(function(x){d.cookie=n+"=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;domain="+x})})}
function revoke(){window["ga-disable-"+ID]=true;gtag("consent","update",{analytics_storage:"denied"});wipe()}
var cb=d.getElementById("cb");
function choose(v){set(CK,v);cb.hidden=true;if(v==="granted")grant();else revoke()}
d.getElementById("cy").onclick=function(){choose("granted")};
d.getElementById("cn").onclick=function(){choose("denied")};
d.getElementById("cs").onclick=function(e){e.preventDefault();cb.hidden=false};
var c=get(CK);if(c==="granted")grant();else if(c!=="denied")cb.hidden=false;
})();`;

export const navI18n = (slug, name) => `<a href="/${slug}/">${name}</a> &middot;
<a href="/${slug}/docs">${L("Docs", "Doku")}</a> &middot;
<a href="/${slug}/support">Support</a> &middot;
<a href="/${slug}/privacy">${L("Privacy", "Datenschutz")}</a> &middot;
<a href="/${slug}/terms">${L("Terms", "Nutzungsbedingungen")}</a>`;

// Wraps a page body. titles = [en, de]. nav = inner HTML of the nav paragraph.
export function shell(slug, titles, style, nav, body) {
  return `<!doctype html><html lang=en><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>${titles[0]}</title>
<meta name=hd-title-de content="${titles[1]}">
<style>${style}${LANG_CSS}</style>
<div class=bar><p class=muted>${nav}</p></div>
<hr>
${body}
${foot(slug)}
<script>${LANG_JS}</script>
</html>`;
}
