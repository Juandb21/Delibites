import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'delibites.settings')
django.setup()

from usuarios.models import Rol, Empleado, Categoria, Producto, Mesa, Zona
from django.contrib.auth.models import User

# Crear roles
roles_data = [
    ('mesero', 'Mesero'),
    ('cocinero', 'Cocinero'),
    ('cajero', 'Cajero'),
    ('administrador', 'Administrador'),
]

for nombre, _ in roles_data:
    Rol.objects.get_or_create(nombre=nombre)

# Crear datos para empleados existentes
usuarios_existentes = User.objects.filter(username__in=['mesero1', 'cocinero1', 'cajero1', 'admin'])
for usuario in usuarios_existentes:
    if not hasattr(usuario, 'empleado'):
        rol_map = {
            'mesero1': 'mesero',
            'cocinero1': 'cocinero',
            'cajero1': 'cajero',
            'admin': 'administrador',
        }
        rol = Rol.objects.get(nombre=rol_map[usuario.username])
        Empleado.objects.create(usuario=usuario, rol=rol)

# Crear categorías
categorias_data = ['Entradas', 'Principales', 'Postres', 'Bebidas']
for nombre in categorias_data:
    Categoria.objects.get_or_create(nombre=nombre)

# Crear productos
productos_data = [
    ('Ensalada César', 'Entradas', 8.500),
    ('Sopa del Día', 'Entradas', 6.000),
    ('Bruschetta', 'Entradas', 7.000),
    ('Alitas de Pollo', 'Entradas', 9.500),
    ('Bandeja Paisa', 'Principales', 18.000),
    ('Lomo de Res', 'Principales', 25.000),
    ('Pechuga a la Plancha', 'Principales', 16.000),
    ('Trucha a la Almendras', 'Principales', 22.000),
]

for nombre, categoria, precio in productos_data:
    cat = Categoria.objects.get(nombre=categoria)
    Producto.objects.get_or_create(nombre=nombre, categoria=cat, defaults={'precio': precio})

# Crear mesas
for i in range(1, 11):
    Mesa.objects.get_or_create(numero=i, defaults={'capacidad': 4})

# Crear zonas
zona_salon, _ = Zona.objects.get_or_create(nombre='Salón Principal', defaults={'color': '#FF6B6B'})
zona_patio, _ = Zona.objects.get_or_create(nombre='Patio', defaults={'color': '#4ECDC4'})

# Asignar mesas a zonas
mesas_salon = Mesa.objects.filter(numero__in=[1, 2, 3, 4])
mesas_patio = Mesa.objects.filter(numero__in=[5, 6, 7, 8, 9, 10])

zona_salon.mesas.set(mesas_salon)
zona_patio.mesas.set(mesas_patio)

print("✓ Datos de ejemplo creados exitosamente")
