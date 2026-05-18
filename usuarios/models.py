from django.db import models
from django.contrib.auth.models import User


class Rol(models.Model):
    """Roles de usuarios del restaurante"""
    ROLES = [
        ('mesero', 'Mesero'),
        ('cocinero', 'Cocinero'),
        ('cajero', 'Cajero'),
        ('administrador', 'Administrador'),
        ('cliente', 'Cliente'),
    ]
    
    nombre = models.CharField(max_length=20, choices=ROLES, unique=True)
    descripcion = models.TextField(blank=True)
    
    class Meta:
        verbose_name_plural = "Roles"
    
    def __str__(self):
        return self.get_nombre_display()


class Empleado(models.Model):
    """Información adicional de empleados"""
    usuario = models.OneToOneField(User, on_delete=models.CASCADE)
    rol = models.ForeignKey(Rol, on_delete=models.SET_NULL, null=True)
    telefono = models.CharField(max_length=20, blank=True)
    fecha_contratacion = models.DateField(auto_now_add=True)
    activo = models.BooleanField(default=True)
    
    def __str__(self):
        return f"{self.usuario.first_name} - {self.rol}"


class Categoria(models.Model):
    """Categorías de productos (Entradas, Platos Principales, etc.)"""
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True)
    
    class Meta:
        verbose_name_plural = "Categorías"
    
    def __str__(self):
        return self.nombre


class Producto(models.Model):
    """Productos/Platos del menú"""
    nombre = models.CharField(max_length=200)
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    descripcion = models.TextField(blank=True)
    disponible = models.BooleanField(default=True)
    imagen = models.ImageField(upload_to='productos/', blank=True, null=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.nombre


class Mesa(models.Model):
    """Mesas del restaurante"""
    ESTADOS_MESA = [
        ('libre', 'Libre'),
        ('ocupada', 'Ocupada'),
        ('reservada', 'Reservada'),
    ]
    
    numero = models.IntegerField(unique=True)
    capacidad = models.IntegerField(default=4)
    ubicacion = models.CharField(max_length=100, blank=True)
    disponible = models.BooleanField(default=True)
    x = models.IntegerField(default=50)
    y = models.IntegerField(default=50)
    width = models.IntegerField(default=100)
    height = models.IntegerField(default=100)
    zona = models.ForeignKey('Zona', on_delete=models.SET_NULL, null=True, blank=True, related_name='mesas_set')
    estado_mesa = models.CharField(max_length=20, choices=ESTADOS_MESA, default='libre')
    
    class Meta:
        verbose_name_plural = "Mesas"
    
    def __str__(self):
        return f"Mesa {self.numero}"


class Zona(models.Model):
    """Zonas/Áreas del restaurante"""
    nombre = models.CharField(max_length=100)
    color = models.CharField(max_length=7, default='#FF0000')  # Color hexadecimal
    x = models.IntegerField(default=0)
    y = models.IntegerField(default=0)
    width = models.IntegerField(default=200)
    height = models.IntegerField(default=150)
    shape = models.CharField(
        max_length=20,
        choices=[
            ('rectangle', 'Rectángulo'),
            ('l-shape', 'Forma de L'),
            ('triangle', 'Triángulo'),
            ('hexagon', 'Hexágono'),
        ],
        default='rectangle'
    )
    descripcion = models.TextField(blank=True)
    
    def __str__(self):
        return self.nombre


class Pedido(models.Model):
    """Pedidos de clientes"""
    ESTADOS = [
        ('pendiente', 'Pendiente'),
        ('en_preparacion', 'En Preparación'),
        ('listo', 'Listo'),
        ('entregado', 'Entregado'),
        ('cancelado', 'Cancelado'),
    ]
    
    numero = models.AutoField(primary_key=True)
    cliente = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    mesa = models.ForeignKey(Mesa, on_delete=models.SET_NULL, null=True, blank=True)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='pendiente')
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_entrega = models.DateTimeField(null=True, blank=True)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notas = models.TextField(blank=True)
    
    def __str__(self):
        return f"Pedido #{self.numero}"


class DetallePedido(models.Model):
    """Detalles de items en un pedido"""
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='detalles')
    producto = models.ForeignKey(Producto, on_delete=models.SET_NULL, null=True)
    cantidad = models.IntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    
    def __str__(self):
        return f"{self.cantidad}x {self.producto.nombre}"


class Venta(models.Model):
    """Registro de ventas"""
    pedido = models.OneToOneField(Pedido, on_delete=models.CASCADE)
    cajero = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    monto_total = models.DecimalField(max_digits=10, decimal_places=2)
    metodo_pago = models.CharField(
        max_length=20,
        choices=[
            ('efectivo', 'Efectivo'),
            ('tarjeta', 'Tarjeta'),
            ('transferencia', 'Transferencia'),
        ],
        default='efectivo'
    )
    fecha_venta = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Venta #{self.pedido.numero}"


class Reserva(models.Model):
    """Reservas de clientes"""
    ESTADOS_RESERVA = [
        ('pendiente', 'Pendiente'),
        ('confirmada', 'Confirmada'),
        ('completada', 'Completada'),
        ('cancelada', 'Cancelada'),
    ]
    
    cliente = models.ForeignKey(User, on_delete=models.CASCADE)
    mesa = models.ForeignKey(Mesa, on_delete=models.SET_NULL, null=True, blank=True)
    pedido = models.OneToOneField(Pedido, on_delete=models.SET_NULL, null=True, blank=True, related_name='reserva')
    nombre_cliente = models.CharField(max_length=200)
    email = models.EmailField()
    telefono = models.CharField(max_length=20)
    cantidad_personas = models.IntegerField()
    fecha_reserva = models.DateField()
    hora_reserva = models.TimeField()
    estado = models.CharField(max_length=20, choices=ESTADOS_RESERVA, default='pendiente')
    recargo_reserva = models.DecimalField(max_digits=10, decimal_places=2, default=10000)
    editable_hasta = models.DateTimeField(null=True, blank=True)
    pedido_enviado_cocina = models.BooleanField(default=False)
    comentarios = models.TextField(blank=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Reserva de {self.nombre_cliente} - {self.fecha_reserva}"
