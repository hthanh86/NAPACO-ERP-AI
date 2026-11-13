"""Register all domain models once for migrations and startup."""
from app.core.database import Base
import app.auth.models
import app.compatibility.models
import app.core.models
import app.core.settings
import app.integrations.google.models
import app.migrations.models
import app.modules.customers.models
import app.modules.materials.inventory.models
import app.modules.materials.models
import app.modules.materials.purchasing.models
import app.modules.materials.receiving.models
import app.modules.orders.models
import app.modules.products.models
import app.modules.production.models
import app.modules.qc.models
import app.modules.qc.template_models
import app.modules.qc.job_models
