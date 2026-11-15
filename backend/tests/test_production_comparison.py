"""Prepared phase-6 targeted cases. Not executed without the user's approval."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from app.modules.production.schedule_compare import metrics,compare_metrics

START=datetime(2026,11,16,8,tzinfo=timezone(timedelta(hours=7)))
END=START+timedelta(hours=8)


def part(*,quantity=10,pure=100,status='Đã kết thúc',machine='DH1',start=START,end=None):
    return {'run_id':'R1','stage':'forming','machine_id':machine,'spans':[{'start':start,'end':end or START+timedelta(minutes=5)}],
        'items':[{'order_line_id':'CT1','good_qty':quantity,'unit':'Cái'}],'pure_seconds':pure,'run_status':status}


def test_missing_journal_is_not_zero_output_or_idle():
    baseline=metrics([part()],START,END)
    row=compare_metrics(baseline,{},'actual')[0]
    assert row['current'] is None
    assert row['data_quality']=='no_data'
    assert row['completion']=='no_data'
    assert row['pure_delta_seconds'] is None


def test_partial_window_does_not_prorate_output_or_pure_time():
    result=metrics([part(start=START-timedelta(minutes=1))],START,END)[('R1','forming')]
    assert result['quantities']['CT1'] is None
    assert result['pure_seconds'] is None
    assert result['scope_complete'] is False


def test_wall_time_and_speed_are_not_substituted_for_missing_pure_time():
    row=compare_metrics(metrics([part()],START,END),metrics([part(pure=None)],START,END),'actual')[0]
    assert row['current']['quantity_complete'] is True
    assert row['current']['pure_seconds'] is None
    assert row['pure_comparable'] is False


def test_open_run_with_sufficient_quantity_still_is_not_final():
    row=compare_metrics(metrics([part()],START,END),metrics([part(status='Đang chạy')],START,END),'actual')[0]
    assert row['completion']=='quantity_reached_run_open'
    assert row['end_delta_seconds'] is None
    assert row['pure_comparable'] is False


def test_closed_run_with_quantity_shortfall_does_not_claim_final_comparable_time():
    row=compare_metrics(metrics([part()],START,END),metrics([part(quantity=5,pure=80)],START,END),'actual')[0]
    assert row['completion']=='not_finished'
    assert row['pure_delta_seconds'] is None


def test_comparison_uses_stable_run_id_and_does_not_modify_baseline():
    source=[part()];before=deepcopy(source)
    row=compare_metrics(metrics(source,START,END),metrics([part(machine='DH2')],START,END),'update')[0]
    assert row['run_id']=='R1'
    assert row['machine_changed'] is True
    assert source==before
