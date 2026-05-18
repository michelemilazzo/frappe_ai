(()=>{(function(){"use strict";if(window._frappAiLoaded)return;window._frappAiLoaded=!0;let f=`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
    </svg>`,E="\xD7",L=`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
        <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
    </svg>`,l=[],u=!1,s=[];function m(){if(document.getElementById("frappe-ai-btn"))return;let e=document.createElement("button");e.id="frappe-ai-btn",e.title="AI Assistant",e.innerHTML=f,e.addEventListener("click",g),document.body.appendChild(e);let a=document.createElement("div");a.id="frappe-ai-panel",a.className="hidden",a.innerHTML=`
            <div id="frappe-ai-header">
                <span>${f} AI Assistant</span>
                <button id="frappe-ai-close" title="Close">${E}</button>
            </div>
            <div id="frappe-ai-messages"></div>
            <div id="frappe-ai-attachments"></div>
            <div id="frappe-ai-footer">
                <button id="frappe-ai-attach" title="Allega file">${L}</button>
                <input type="file" id="frappe-ai-file-input" style="display:none"
                    accept=".txt,.md,.csv,.json,.py,.js,.html,.xml,.sql,.log,.pdf,.docx,.xlsx" multiple>
                <textarea id="frappe-ai-input" placeholder="Scrivi un messaggio\u2026" rows="1"></textarea>
                <button id="frappe-ai-send">\u27A4</button>
            </div>
        `,document.body.appendChild(a),document.getElementById("frappe-ai-close").addEventListener("click",g),document.getElementById("frappe-ai-send").addEventListener("click",h),document.getElementById("frappe-ai-attach").addEventListener("click",function(){document.getElementById("frappe-ai-file-input").click()}),document.getElementById("frappe-ai-file-input").addEventListener("change",b),document.getElementById("frappe-ai-input").addEventListener("keydown",function(t){t.key==="Enter"&&!t.shiftKey&&(t.preventDefault(),h())}),d("assistant","Ciao! Sono l'assistente AI. Come posso aiutarti con Frappe/ERPNext?")}function b(e){Array.from(e.target.files).forEach(function(t){let i=new FileReader;i.onload=function(c){let n=c.target.result;typeof n!="string"&&(n="[file binary]"),s.push({name:t.name,content:n.slice(0,8e3)}),p()};let r=t.name.split(".").pop().toLowerCase();["pdf"].includes(r)?(s.push({name:t.name,content:"[PDF allegato \u2014 il contenuto non pu\xF2 essere estratto lato client]"}),p()):i.readAsText(t,"UTF-8")}),e.target.value=""}function p(){let e=document.getElementById("frappe-ai-attachments");e.innerHTML="",s.forEach(function(a,t){let i=document.createElement("span");i.className="ai-attachment-chip",i.innerHTML=`\u{1F4CE} ${a.name} <button data-idx="${t}">\xD7</button>`,i.querySelector("button").addEventListener("click",function(){s.splice(t,1),p()}),e.appendChild(i)})}function g(){u=!u;let e=document.getElementById("frappe-ai-panel");u?(e.classList.remove("hidden"),document.getElementById("frappe-ai-input").focus()):e.classList.add("hidden")}function d(e,a){let t=document.getElementById("frappe-ai-messages"),i=document.createElement("div");return i.className=`ai-msg ${e}`,i.innerHTML=I(a),t.appendChild(i),t.scrollTop=t.scrollHeight,i}function I(e){return e.replace(/```([\s\S]*?)```/g,"<pre><code>$1</code></pre>").replace(/`([^`]+)`/g,"<code>$1</code>").replace(/\*\*(.*?)\*\*/g,"<strong>$1</strong>").replace(/\n/g,"<br>")}function h(){let e=document.getElementById("frappe-ai-input"),a=e.value.trim();if(!a&&s.length===0)return;let t=a;if(s.length>0){let n=s.map(function(o){return`

--- File: ${o.name} ---
${o.content}`}).join(`
`);t=(a?a+`
`:"")+n}e.value="",e.style.height="38px";let i=a+(s.length>0?`
`+s.map(n=>`\u{1F4CE} ${n.name}`).join(", "):"");d("user",i),l.push({role:"user",content:t}),s=[],p();let r=document.getElementById("frappe-ai-send");r.disabled=!0;let c=d("assistant","\u2026");c.classList.add("typing"),frappe.call({method:"frappe_ai.api.chat.send_message",args:{message:t,history:l.slice(-10)},callback:function(n){if(c.remove(),r.disabled=!1,n.message&&n.message.reply){let o=n.message.reply;d("assistant",o),l.push({role:"assistant",content:o}),l.length>20&&(l=l.slice(-20))}else d("assistant","\u26A0\uFE0F Nessuna risposta dal provider AI. Controlla la configurazione in AI Settings.")},error:function(n){var v,y;c.remove(),r.disabled=!1;let o=(v=n==null?void 0:n.responseJSON)!=null&&v._server_messages?(y=JSON.parse(n.responseJSON._server_messages)[0])==null?void 0:y.message:"Errore di connessione.";d("assistant","\u26A0\uFE0F "+(o||"Errore sconosciuto."))}})}document.addEventListener("input",function(e){e.target.id==="frappe-ai-input"&&(e.target.style.height="38px",e.target.style.height=Math.min(e.target.scrollHeight,100)+"px")}),typeof frappe!="undefined"&&frappe.ui?m():document.addEventListener("DOMContentLoaded",function(){setTimeout(m,1500)})})();})();
//# sourceMappingURL=frappe_ai.bundle.APNF6ZED.js.map
