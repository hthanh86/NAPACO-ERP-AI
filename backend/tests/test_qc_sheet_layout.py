from copy import deepcopy
from app.modules.qc.sheets_layout import fit_content, wrapped_lines, font_name


def snapshot():
    return {'row_count':8,'column_count':4,'grid':{
        'rowMetadata':[{'pixelSize':20} for _ in range(8)],
        'columnMetadata':[{'pixelSize':100} for _ in range(4)],
        'rowData':[{'values':[{'formattedValue':'','effectiveFormat':{'wrapStrategy':'WRAP','textFormat':{'fontSize':10,'fontFamily':'Times New Roman'}}} for _ in range(4)]} for _ in range(8)]},
        'merges':[{'startRowIndex':3,'endRowIndex':5,'startColumnIndex':0,'endColumnIndex':3},
                  {'startRowIndex':6,'endRowIndex':8,'startColumnIndex':0,'endColumnIndex':4}]}


def test_multiline_and_merged_notes_grow_rows_without_touching_original_or_signature():
    data=snapshot();before=deepcopy(data)
    values={'D2':'Dòng một\nDòng hai\n\nDòng bốn\nDòng năm', 'A4':'Ghi chú một\nGhi chú hai\nGhi chú ba\nGhi chú bốn'}
    requests=fit_content(data,{'signature_cell':'A7','signature_end_cell':'D8'},values,42)
    heights={r['updateDimensionProperties']['range']['startIndex']:r['updateDimensionProperties']['properties']['pixelSize'] for r in requests if 'updateDimensionProperties' in r}
    assert heights[1]>=100
    assert heights[4]+20>=80  # A4:C5: increase the last row of the merged region.
    assert 6 not in heights and 7 not in heights
    assert all(r.get('repeatCell',{}).get('fields','')=='userEnteredFormat.wrapStrategy' for r in requests if 'repeatCell' in r)
    assert data==before


def test_wrapping_uses_merged_width_and_never_shrinks_rows():
    data=snapshot();data['grid']['rowMetadata'][1]['pixelSize']=200
    requests=fit_content(data,{'signature_cell':'A7','signature_end_cell':'D8'},{'D2':'Short','A4':'Words repeated '*4},42)
    assert not any(r.get('updateDimensionProperties',{}).get('range',{}).get('startIndex')==1 for r in requests)
    font=font_name({'fontFamily':'Arial'})
    assert wrapped_lines('a\nb\n',font,10,100)==3
    assert wrapped_lines('ABCDEFGHIJK'*10,font,10,50)>5
    assert wrapped_lines('word '*15,font,10,300)<wrapped_lines('word '*15,font,10,100)
