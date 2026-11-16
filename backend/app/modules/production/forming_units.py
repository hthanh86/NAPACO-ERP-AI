"""Forming quantities count pieces; downstream sheet/metre units are separate."""
def is_piece_unit(value):
    return str(value or '').strip().casefold() in {'cái','chiếc'}
