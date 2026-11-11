"""Composition of module-owned MySQL mappings. No business rules here."""
from app.modules.customers.legacy_adapter import TABLES as TABLES_0
from app.modules.products.legacy_adapter import TABLES as TABLES_1
from app.auth.legacy_adapter import TABLES as TABLES_2
from app.modules.orders.legacy_adapter import TABLES as TABLES_3
from app.modules.materials.legacy_adapter import TABLES as TABLES_4
from app.modules.materials.purchasing.legacy_adapter import TABLES as TABLES_5
from app.modules.materials.receiving.legacy_adapter import TABLES as TABLES_6
from app.modules.materials.inventory.legacy_adapter import TABLES as TABLES_7

TABLE_SPECS = {
    **TABLES_0,
    **TABLES_1,
    **TABLES_2,
    **TABLES_3,
    **TABLES_4,
    **TABLES_5,
    **TABLES_6,
    **TABLES_7,
}
