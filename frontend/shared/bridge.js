/* Transport only: original screens, event handlers and business payloads are unchanged. */
(()=>{
  const writes=new Set(['saveOrderTransaction','saveOrderFromModal','submitOrderTransaction','updateOrderLineItemsBulk','apiUpdateLineKanbanPositions','saveFilmAssignments','saveFilmOrder','saveFilmReceipts','saveFilmReceipt','confirmFilmReturn','syncFilmReturnFromJournal']);
  const revisions=new Set(['queryOrdersAndLineItems','getOrderModalInitData','getOrderFormData','getFilmOrders','getFilmOrderFormData','getFilmReceiptLines','getFilmStock']);
  const pending=new Map();
  function runner(success=()=>{},failure=error=>console.error(error)){
    return new Proxy({}, {get(_,method){
      if(method==='withSuccessHandler')return fn=>runner(fn,failure);
      if(method==='withFailureHandler')return fn=>runner(success,fn);
      if(typeof method!=='string')return undefined;
      return (...args)=>{
        const isWrite=writes.has(method), key=isWrite?method+':'+JSON.stringify(args):'';
        const requestId=isWrite?(pending.get(key)||crypto.randomUUID()):crypto.randomUUID();
        if(isWrite)pending.set(key,requestId);
        fetch('/api/legacy/'+encodeURIComponent(method),{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({args,revision:window.NAPACO_REV,request_id:requestId})})
        .then(async response=>{const data=await response.json();if(!response.ok){
          if(response.status===401)location.href='/login?next='+encodeURIComponent(location.pathname+location.search);
          throw new Error(typeof data.detail==='string'?data.detail:'Không thực hiện được yêu cầu.');}
          if(isWrite||revisions.has(method))window.NAPACO_REV=data.revision;
          if(isWrite)pending.delete(key);
          return data.result;}).then(success).catch(failure);
      };
    }});
  }
  window.google={script:{get run(){return runner();},host:{close(){location.href='/?view=index';}}}};
})();
