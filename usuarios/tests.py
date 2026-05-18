import json
from decimal import Decimal
from datetime import date, time, timedelta

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import ProductoForm
from .models import Categoria, DetallePedido, Empleado, Mesa, Pedido, Producto, Reserva, Rol, Venta, Zona
from .views import actualizar_estado_mesa


class GuardarMesasTests(TestCase):
    def setUp(self):
        rol = Rol.objects.create(nombre='administrador')
        self.user = User.objects.create_user(username='admin', password='admin123')
        Empleado.objects.create(usuario=self.user, rol=rol)
        self.client.login(username='admin', password='admin123')
        self.zona = Zona.objects.create(nombre='Salon', color='#5B6EFF', x=10, y=20, width=300, height=200)

    def post_mesas(self, mesas):
        return self.client.post(
            reverse('guardar_mesas'),
            data=json.dumps({'mesas': mesas}),
            content_type='application/json',
        )

    def test_crea_mesa_nueva_con_id_temporal(self):
        response = self.post_mesas([
            {
                'id': -1,
                'numero': 12,
                'capacidad': 4,
                'x': 50,
                'y': 60,
                'width': 94,
                'height': 94,
                'zona_id': self.zona.id,
            }
        ])

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['created'], 1)
        mesa = Mesa.objects.get(numero=12)
        self.assertEqual(mesa.zona, self.zona)
        self.assertEqual(mesa.x, 50)
        self.assertEqual(payload['mesas'][0]['temp_id'], -1)
        self.assertEqual(payload['mesas'][0]['id'], mesa.id)

    def test_rechaza_numero_de_mesa_duplicado(self):
        Mesa.objects.create(numero=7, capacidad=4, zona=self.zona)

        response = self.post_mesas([
            {
                'id': -1,
                'numero': 7,
                'capacidad': 2,
                'x': 30,
                'y': 40,
                'width': 94,
                'height': 94,
                'zona_id': self.zona.id,
            }
        ])

        self.assertEqual(response.status_code, 400)
        self.assertIn('Ya existe una mesa', response.json()['error'])
        self.assertEqual(Mesa.objects.filter(numero=7).count(), 1)


class EstadoMesaTests(TestCase):
    def setUp(self):
        rol = Rol.objects.create(nombre='administrador')
        self.user = User.objects.create_user(username='admin', password='admin123')
        Empleado.objects.create(usuario=self.user, rol=rol)
        self.client.login(username='admin', password='admin123')
        self.mesa = Mesa.objects.create(numero=3, capacidad=4)

    def test_mesa_entregada_sigue_ocupada_hasta_el_pago(self):
        pedido = Pedido.objects.create(
            cliente=self.user,
            mesa=self.mesa,
            estado='entregado',
            total=Decimal('25000'),
            notas='Cliente',
        )

        actualizar_estado_mesa(self.mesa)
        self.mesa.refresh_from_db()
        self.assertEqual(self.mesa.estado_mesa, 'ocupada')

        Venta.objects.create(
            pedido=pedido,
            cajero=self.user,
            monto_total=pedido.total,
            metodo_pago='efectivo',
        )
        actualizar_estado_mesa(self.mesa)
        self.mesa.refresh_from_db()
        self.assertEqual(self.mesa.estado_mesa, 'libre')

    def test_endpoint_estado_mesas_reporta_ocupada_si_hay_cuenta_pendiente(self):
        Pedido.objects.create(
            cliente=self.user,
            mesa=self.mesa,
            estado='listo',
            total=Decimal('12000'),
            notas='Cliente',
        )

        response = self.client.get(reverse('estado_mesas'))

        self.assertEqual(response.status_code, 200)
        mesa_data = next(item for item in response.json()['mesas'] if item['id'] == self.mesa.id)
        self.assertEqual(mesa_data['estado'], 'ocupada')


class ReservasHorarioTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='cliente', password='cliente123', first_name='Cliente')
        self.client.login(username='cliente', password='cliente123')
        self.zona = Zona.objects.create(nombre='Salon')
        self.mesa = Mesa.objects.create(numero=20, capacidad=4, zona=self.zona)
        categoria = Categoria.objects.create(nombre='Entradas')
        self.producto = Producto.objects.create(
            nombre='Alitas',
            categoria=categoria,
            precio=Decimal('9500'),
            disponible=True,
        )
        self.fecha = timezone.localdate() + timedelta(days=1)

    def reserva_payload(self, hora):
        return {
            'mesa_id': self.mesa.id,
            'nombre': 'Cliente',
            'email': 'cliente@example.com',
            'telefono': '123',
            'personas': 2,
            'fecha': self.fecha.isoformat(),
            'hora': hora,
            'items_json': json.dumps([{'producto_id': self.producto.id, 'cantidad': 1}]),
        }

    def test_rechaza_reserva_si_se_cruza_con_otra_en_menos_de_una_hora(self):
        pedido = Pedido.objects.create(
            cliente=self.user,
            mesa=self.mesa,
            estado='pendiente',
            total=Decimal('19500'),
            notas='Cliente',
        )
        DetallePedido.objects.create(
            pedido=pedido,
            producto=self.producto,
            cantidad=1,
            precio_unitario=self.producto.precio,
            subtotal=self.producto.precio,
        )
        Reserva.objects.create(
            cliente=self.user,
            mesa=self.mesa,
            pedido=pedido,
            nombre_cliente='Cliente',
            email='cliente@example.com',
            telefono='123',
            cantidad_personas=2,
            fecha_reserva=self.fecha,
            hora_reserva=time(15, 15),
            editable_hasta=timezone.now() + timedelta(minutes=10),
        )

        response = self.client.post(reverse('reservas'), self.reserva_payload('15:45'), follow=True)

        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any('Cada reserva ocupa 1 hora' in message for message in messages))
        self.assertEqual(Reserva.objects.count(), 1)

    def test_permite_reserva_justo_una_hora_despues(self):
        other_user = User.objects.create_user(username='otro', password='otro123')
        pedido = Pedido.objects.create(
            cliente=other_user,
            mesa=self.mesa,
            estado='pendiente',
            total=Decimal('19500'),
            notas='Otro',
        )
        DetallePedido.objects.create(
            pedido=pedido,
            producto=self.producto,
            cantidad=1,
            precio_unitario=self.producto.precio,
            subtotal=self.producto.precio,
        )
        Reserva.objects.create(
            cliente=other_user,
            mesa=self.mesa,
            pedido=pedido,
            nombre_cliente='Otro',
            email='otro@example.com',
            telefono='456',
            cantidad_personas=2,
            fecha_reserva=self.fecha,
            hora_reserva=time(15, 15),
        )

        response = self.client.post(reverse('reservas'), self.reserva_payload('16:15'), follow=True)

        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertFalse(any('Cada reserva ocupa 1 hora' in message for message in messages))
        self.assertEqual(Reserva.objects.count(), 2)


class ProductoFormTests(TestCase):
    def test_producto_form_crea_producto(self):
        categoria = Categoria.objects.create(nombre='Bebidas')
        form = ProductoForm(data={
            'nombre': 'Limonada',
            'categoria': categoria.id,
            'precio': '6000',
            'descripcion': 'EEE',
            'disponible': 'on',
        })

        self.assertTrue(form.is_valid(), form.errors)
        producto = form.save()

        self.assertEqual(producto.nombre, 'Limonada')
        self.assertEqual(producto.categoria, categoria)
        self.assertEqual(producto.precio, Decimal('6000'))


class ProductoImagenMenuTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='cliente', password='cliente123')
        self.client.login(username='cliente', password='cliente123')
        categoria = Categoria.objects.create(nombre='Bebidas')
        Producto.objects.create(
            nombre='Limonada',
            categoria=categoria,
            precio=Decimal('6000'),
            imagen='productos/limonada.jpg',
            disponible=True,
        )

    def test_reservas_envia_url_de_imagen_del_producto(self):
        response = self.client.get(reverse('reservas'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '/media/productos/limonada.jpg')
