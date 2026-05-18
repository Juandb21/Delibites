import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'delibites.settings')
django.setup()

from usuarios.models import Mesa, Zona

# Obtener zonas
zonas = Zona.objects.all()
salón_principal = zonas.filter(nombre='Salón Principal').first()
patio = zonas.filter(nombre='Patio').first()

# Actualizar mesas con posiciones iniciales
mesas_data = [
    (1, 100, 100, salón_principal),
    (2, 250, 100, salón_principal),
    (3, 100, 250, salón_principal),
    (4, 250, 250, salón_principal),
    (5, 450, 100, patio),
    (6, 600, 100, patio),
    (7, 450, 250, patio),
    (8, 600, 250, patio),
    (9, 750, 100, patio),
    (10, 750, 250, patio),
]

for numero, x, y, zona in mesas_data:
    mesa = Mesa.objects.get(numero=numero)
    mesa.x = x
    mesa.y = y
    mesa.width = 100
    mesa.height = 100
    mesa.zona = zona
    mesa.estado_mesa = 'libre'
    mesa.save()
    print(f"✓ Mesa {numero} actualizada: zona={zona.nombre if zona else 'Sin zona'}, pos=({x}, {y})")

print("\n✅ Todas las mesas han sido actualizadas")
