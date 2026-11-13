/* Read-only DOM renderer: Google text never becomes HTML, CSS rules or formulas. */
(() => {
  const el = (tag, text) => {const node = document.createElement(tag); if (text != null) node.textContent = text; return node;};
  const bound = (value, fallback, min, max) => Number.isFinite(value) ? Math.max(min, Math.min(max, value)) : fallback;
  function letters(index) {
    let label = '';
    for (let n = index + 1; n; n = Math.floor((n - 1) / 26)) label = String.fromCharCode(65 + (n - 1) % 26) + label;
    return label;
  }
  function range(data,start,end=start){
    const position=value=>{
      const match=/^([A-Z]{1,2})([1-9][0-9]{0,2})$/.exec(value||'');if(!match)return null;
      let col=0;for(const ch of match[1])col=col*26+ch.charCodeAt(0)-64;
      const row=Number(match[2])-1;return row<data.row_count&&col<=data.column_count?[row,col-1]:null;
    };
    const a=position(start),b=position(end);if(!a||!b)return null;
    let r0=Math.min(a[0],b[0]),c0=Math.min(a[1],b[1]),r1=Math.max(a[0],b[0])+1,c1=Math.max(a[1],b[1])+1,changed;
    do{
      changed=false;
      for(const merge of data.merges||[]){
        const r=merge.startRowIndex||0,c=merge.startColumnIndex||0,x=merge.endRowIndex,y=merge.endColumnIndex;
        if(r<r1&&x>r0&&c<c1&&y>c0&&(r<r0||c<c0||x>r1||y>c1)){
          r0=Math.min(r0,r);c0=Math.min(c0,c);r1=Math.max(r1,x);c1=Math.max(c1,y);changed=true;
        }
      }
    }while(changed);
    return {r0,c0,r1,c1,start:letters(c0)+(r0+1),end:letters(c1-1)+r1};
  }
  function render(container, data, options = {}) {
    const theme = Object.fromEntries((data.theme?.themeColors || []).map(item => [item.colorType, item.color?.rgbColor]));
    function color(rgb, style) {
      const value = style?.rgbColor || theme[style?.themeColor] || rgb;
      if (!value) return '';
      return 'rgb(' + ['red','green','blue'].map(key => Math.round(bound(value[key] ?? 0, 0, 0, 1) * 255)).join(',') + ')';
    }
    function format(cell, value) {
      const f = value.effectiveFormat || {}, text = f.textFormat || {}, s = cell.style;
      s.backgroundColor = color(f.backgroundColor, f.backgroundColorStyle);
      s.color = color(text.foregroundColor, text.foregroundColorStyle);
      s.fontFamily = text.fontFamily || 'Arial';
      s.fontSize = bound(text.fontSize, 10, 6, 96) + 'pt';
      s.fontWeight = text.bold ? '700' : '400'; s.fontStyle = text.italic ? 'italic' : 'normal';
      s.textDecoration = [text.underline && 'underline',text.strikethrough && 'line-through'].filter(Boolean).join(' ') || 'none';
      s.textAlign = {LEFT:'left',CENTER:'center',RIGHT:'right'}[f.horizontalAlignment] || 'left';
      s.verticalAlign = {TOP:'top',MIDDLE:'middle',BOTTOM:'bottom'}[f.verticalAlignment] || 'bottom';
      s.whiteSpace = f.wrapStrategy === 'WRAP' ? 'pre-wrap' : 'pre';
      for (const edge of ['top','bottom','left','right']) {
        const b = f.borders?.[edge]; if (!b) continue;
        const styles = {DOTTED:'1px dotted',DASHED:'1px dashed',SOLID:'1px solid',SOLID_MEDIUM:'2px solid',SOLID_THICK:'3px solid',DOUBLE:'3px double',NONE:'0 none'};
        if (styles[b.style]) s['border' + edge[0].toUpperCase() + edge.slice(1)] = styles[b.style] + ' ' + (color(b.color,b.colorStyle) || '#000');
      }
    }
    const grid = data.grid || {}, rows = grid.rowData || [], rowStart = grid.startRow || 0, colStart = grid.startColumn || 0;
    const merges = (data.merges || []).filter(m => (m.startRowIndex || 0) < data.row_count && (m.startColumnIndex || 0) < data.column_count);
    const rowCount = Math.min(data.row_count, options.selectable ? data.row_count : Math.max(1, rowStart + rows.length, ...merges.map(m => m.endRowIndex)));
    const colCount = Math.min(data.column_count, options.selectable ? data.column_count : Math.max(1, ...rows.map(r => colStart + (r.values || []).length), ...merges.map(m => m.endColumnIndex)));
    const covered = new Set(), anchors = new Map();
    for (const m of merges) {
      const r0 = m.startRowIndex || 0, c0 = m.startColumnIndex || 0;
      anchors.set(r0 + ':' + c0, {rows:Math.min(m.endRowIndex,rowCount)-r0,cols:Math.min(m.endColumnIndex,colCount)-c0});
      for (let r=r0;r<Math.min(m.endRowIndex,rowCount);r++) for (let c=c0;c<Math.min(m.endColumnIndex,colCount);c++) if(r!==r0||c!==c0) covered.add(r+':'+c);
    }
    const table = el('table'); table.className = 'google-sheet';
    let dragStart=null,lastRange='';
    function selectRange(cell){const area=range(data,dragStart,cell);if(area&&lastRange!==area.start+':'+area.end){lastRange=area.start+':'+area.end;options.onRangeSelect(area.start,area.end);}}
    function finishRange(){dragStart=null;document.removeEventListener('pointermove',moveRange);document.removeEventListener('pointerup',finishRange);document.removeEventListener('pointercancel',finishRange);}
    function moveRange(event){
      if(!dragStart)return;
      const cell=document.elementFromPoint(event.clientX,event.clientY)?.closest('[data-cell]');
      if(cell&&table.contains(cell)){event.preventDefault();selectRange(cell.dataset.cell);}
    }
    const cols = el('colgroup'); cols.append(el('col'));
    for(let c=0;c<colCount;c++) {
      const col = el('col'), meta = grid.columnMetadata?.[c-colStart] || {};
      col.style.width = bound(meta.pixelSize,100,20,1000) + 'px';
      if(meta.hiddenByUser) col.style.visibility = 'collapse';
      cols.append(col);
    }
    table.append(cols); const head = el('thead'), header = el('tr'); header.append(el('th',''));
    for(let c=0;c<colCount;c++) header.append(el('th',letters(c)));
    head.append(header); table.append(head); const body = el('tbody');
    for(let r=0;r<rowCount;r++) {
      const tr=el('tr'), meta=grid.rowMetadata?.[r-rowStart] || {};
      tr.style.height=bound(meta.pixelSize,21,14,1000)+'px';
      if(meta.hiddenByUser || meta.hiddenByFilter) tr.hidden=true;
      const number=el('th',r+1); number.scope='row'; tr.append(number);
      for(let c=0;c<colCount;c++) {
        const key=r+':'+c; if(covered.has(key)) continue;
        const value=rows[r-rowStart]?.values?.[c-colStart] || {}, cell=el('td');
        const cellAddress = letters(c) + (r+1); cell.dataset.cell=cellAddress;
        const content=el('div',value.formattedValue ?? ''); cell.append(content);
        const merge=anchors.get(key); if(merge) {cell.rowSpan=merge.rows;cell.colSpan=merge.cols;}
        format(cell,value);
        if (options.onSelect) {
          cell.tabIndex=0; cell.setAttribute('aria-label','Ô '+cellAddress);
          cell.onclick=()=>{if(!options.canSelectRange?.())options.onSelect(cellAddress);};
          cell.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();options.onSelect(cellAddress);}};
        }
        if(options.onRangeSelect)cell.onpointerdown=event=>{
          if(event.button!==0||!options.canSelectRange?.())return;
          event.preventDefault();dragStart=cellAddress;lastRange='';selectRange(cellAddress);
          document.addEventListener('pointermove',moveRange,{passive:false});document.addEventListener('pointerup',finishRange);document.addEventListener('pointercancel',finishRange);
        };
        tr.append(cell);
      }
      body.append(tr);
    }
    table.append(body); container.replaceChildren(table);
  }
  window.QCSheetPreview = {render,range};
})();
