document.addEventListener("click", function(e){
    const el = e.target.closest("[data-event]");
    if(!el) return;

    fetch("/api/event", {
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({
            event_type:el.dataset.event,
            details:el.dataset.details || ""
        })
    }).catch(()=>{});
});
