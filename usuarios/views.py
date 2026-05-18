from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, Count, Q, OuterRef, Subquery, Exists, Prefetch, F
from django.db.models.functions import TruncDate, TruncHour
from django.http import JsonResponse
from django.core.exceptions import ValidationError
import json
from decimal import Decimal
from datetime import datetime, timedelta, time
from .forms import CustomAuthenticationForm, RegistroClienteForm, EmpleadoForm, ProductoForm
from .models import Producto, Empleado, Pedido, DetallePedido, Venta, Mesa, Zona, Reserva, Categoria


def pedidos_pendientes_pago_queryset():
    return Pedido.objects.filter(
        mesa__isnull=False,
        venta__isnull=True,
    ).exclude(
        estado='cancelado',
    )


@require_http_methods(["GET", "POST"])
def login_view(request):
    """
    Vista para manejar el login de usuarios
    """
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        form = CustomAuthenticationForm(data=request.POST)
        
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f'¡Bienvenido {user.first_name or user.username}!')
            return redirect('dashboard')
        else:
            # Mostrar errores del formulario
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, str(error))
    else:
        form = CustomAuthenticationForm()
    
    context = {
        'form': form,
        'title': 'Iniciar Sesión - Restaurant DeliBites'
    }
    
    return render(request, 'login.html', context)


@require_http_methods(["GET", "POST"])
def registro_view(request):
    """
    Vista para que clientes se registren
    """
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        form = RegistroClienteForm(request.POST)
        
        if form.is_valid():
            user = form.save()
            messages.success(request, '¡Registrado exitosamente! Ahora inicia sesión con tus credenciales.')
            return redirect('login')
        else:
            # Mostrar errores del formulario
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, str(error))
    else:
        form = RegistroClienteForm()
    
    context = {
        'form': form,
        'title': 'Registrarse - Restaurant DeliBites'
    }
    
    return render(request, 'registro.html', context)


@login_required(login_url='login')
def dashboard(request):
    """
    Vista del dashboard principal después del login
    Redirige automáticamente a admin si el usuario es administrador
    """
    try:
        empleado = Empleado.objects.get(usuario=request.user)
        if empleado.rol.nombre == 'administrador':
            return redirect('admin_panel')
        if empleado.rol.nombre == 'cocinero':
            return cocina_dashboard(request)
        if empleado.rol.nombre == 'cajero':
            return caja_dashboard(request)
    except Empleado.DoesNotExist:
        return reservas(request)
    
    active_order_query = pedidos_pendientes_pago_queryset().filter(
        mesa=OuterRef('pk')
    ).order_by('-fecha_creacion')
    mesa_queryset = Mesa.objects.annotate(
        has_active_order=Exists(active_order_query),
        titular_ocupada=Subquery(active_order_query.values('notas')[:1]),
    ).order_by('numero')
    zonas = Zona.objects.prefetch_related(Prefetch('mesas_set', queryset=mesa_queryset)).all()
    mesas = mesa_queryset.select_related('zona')
    categorias = Categoria.objects.prefetch_related('producto_set').all()
    productos_menu = []
    for categoria in categorias:
        for producto in categoria.producto_set.filter(disponible=True).order_by('nombre'):
            productos_menu.append({
                'id': producto.id,
                'nombre': producto.nombre,
                'categoria': categoria.nombre,
                'precio': float(producto.precio),
                'precio_display': f'${producto.precio:,.0f}'.replace(',', '.'),
                'imagen_url': producto.imagen.url if producto.imagen else '',
            })

    pedidos_activos = pedidos_pendientes_pago_queryset().select_related('mesa').prefetch_related('detalles__producto').order_by('-fecha_creacion')

    pedidos_por_mesa = {}
    for pedido in pedidos_activos:
        pedidos_por_mesa.setdefault(str(pedido.mesa.numero), []).append({
            'numero': pedido.numero,
            'cliente': pedido.notas,
            'estado': pedido.estado,
            'estado_display': pedido.get_estado_display(),
            'hora': timezone.localtime(pedido.fecha_creacion).strftime('%I:%M %p').lower(),
            'total': float(pedido.total),
            'total_display': f'${pedido.total:,.0f}'.replace(',', '.'),
            'detalles': [
                {
                    'producto': detalle.producto.nombre if detalle.producto else 'Producto eliminado',
                    'cantidad': detalle.cantidad,
                    'subtotal': float(detalle.subtotal),
                    'subtotal_display': f'${detalle.subtotal:,.0f}'.replace(',', '.'),
                }
                for detalle in pedido.detalles.all()
            ],
        })

    context = {
        'user': request.user,
        'title': 'Panel de Mesero - Restaurant DeliBites',
        'zonas': zonas,
        'mesas': mesas,
        'categorias': categorias,
        'productos_menu_json': json.dumps(productos_menu),
        'pedidos_por_mesa_json': json.dumps(pedidos_por_mesa),
    }
    
    return render(request, 'dashboard.html', context)


def money_cop(value):
    return f'${Decimal(value or 0):,.0f}'.replace(',', '.')


def metodo_pago_display(venta):
    return 'Transacción' if venta.metodo_pago == 'transferencia' else venta.get_metodo_pago_display()


def reservation_datetime(reserva):
    return timezone.make_aware(datetime.combine(reserva.fecha_reserva, reserva.hora_reserva))


def reservation_window_bounds(reserva_dt):
    return reserva_dt, reserva_dt + timedelta(hours=1)


def promote_reservation_orders():
    now = timezone.now()
    kitchen_cutoff = now + timedelta(minutes=30)
    reservas = Reserva.objects.select_related('pedido').filter(
        estado__in=['pendiente', 'confirmada'],
        pedido__estado='pendiente',
        pedido_enviado_cocina=False,
    )
    for reserva in reservas:
        if reservation_datetime(reserva) <= kitchen_cutoff:
            reserva.pedido.estado = 'en_preparacion'
            reserva.pedido.save(update_fields=['estado'])
            reserva.pedido_enviado_cocina = True
            reserva.estado = 'confirmada'
            reserva.save(update_fields=['pedido_enviado_cocina', 'estado'])


def caja_dashboard(request):
    pedidos = Pedido.objects.filter(
        mesa__isnull=False,
    ).exclude(
        estado='cancelado'
    ).filter(
        venta__isnull=True
    ).select_related('mesa').prefetch_related('detalles__producto').order_by('mesa__numero', 'fecha_creacion')

    mesas = {}
    for pedido in pedidos:
        key = str(pedido.mesa.numero)
        mesa_data = mesas.setdefault(key, {
            'numero': pedido.mesa.numero,
            'cliente': pedido.notas or 'Cliente',
            'pedidos_count': 0,
            'pendientes_entrega_count': 0,
            'total': Decimal('0'),
            'pedidos': [],
        })
        mesa_data['pedidos_count'] += 1
        if pedido.estado not in ['listo', 'entregado']:
            mesa_data['pendientes_entrega_count'] += 1
        mesa_data['total'] += pedido.total
        mesa_data['pedidos'].append({
            'numero': pedido.numero,
            'estado': pedido.estado,
            'estado_display': pedido.get_estado_display(),
            'hora': timezone.localtime(pedido.fecha_creacion).strftime('%I:%M %p').lower(),
            'subtotal': float(pedido.total),
            'subtotal_display': money_cop(pedido.total),
            'detalles': [
                {
                    'cantidad': detalle.cantidad,
                    'producto': detalle.producto.nombre if detalle.producto else 'Producto eliminado',
                    'subtotal': float(detalle.subtotal),
                    'subtotal_display': money_cop(detalle.subtotal),
                }
                for detalle in pedido.detalles.all()
            ],
        })

    mesas_caja = []
    for mesa in mesas.values():
        propina = mesa['total'] * Decimal('0.10')
        total_sugerido = mesa['total'] + propina
        total_display = money_cop(mesa['total'])
        mesa.update({
            'total': float(mesa['total']),
            'total_float': float(mesa['total']),
            'total_display': total_display,
            'propina_display': money_cop(propina),
            'total_sugerido_display': money_cop(total_sugerido),
            'puede_pagar': mesa['pendientes_entrega_count'] == 0,
        })
        mesas_caja.append(mesa)

    context = {
        'user': request.user,
        'title': 'Panel de Caja - Restaurant DeliBites',
        'mesas_caja': mesas_caja,
        'mesas_caja_json': json.dumps(mesas_caja),
    }
    return render(request, 'caja.html', context)


@login_required(login_url='login')
@require_http_methods(["POST"])
def procesar_pago(request):
    try:
        empleado = Empleado.objects.get(usuario=request.user)
        if empleado.rol.nombre != 'cajero':
            return JsonResponse({'success': False, 'error': 'No tienes permisos para procesar pagos.'}, status=403)
    except Empleado.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'No tienes permisos para procesar pagos.'}, status=403)

    try:
        data = json.loads(request.body)
        mesa_numero = data.get('mesa_numero')
        metodo_pago = data.get('metodo_pago')
        if metodo_pago not in ['efectivo', 'tarjeta', 'transferencia']:
            return JsonResponse({'success': False, 'error': 'Selecciona un método de pago válido.'}, status=400)

        pedidos = list(Pedido.objects.filter(
            mesa__numero=mesa_numero,
            venta__isnull=True,
        ).exclude(
            estado='cancelado'
        ).select_related('mesa'))

        if not pedidos:
            return JsonResponse({'success': False, 'error': 'Esta mesa no tiene pedidos pendientes de pago.'}, status=400)

        pedidos_sin_entregar = [pedido for pedido in pedidos if pedido.estado not in ['listo', 'entregado']]
        if pedidos_sin_entregar:
            return JsonResponse({
                'success': False,
                'error': 'No se puede procesar el pago hasta que todos los pedidos de la mesa estén listos para entregar.'
            }, status=400)

        venta_ids = []
        with transaction.atomic():
            mesa = pedidos[0].mesa
            for pedido in pedidos:
                if pedido.estado == 'listo':
                    pedido.estado = 'entregado'
                    pedido.fecha_entrega = timezone.now()
                    pedido.save(update_fields=['estado', 'fecha_entrega'])
                venta = Venta.objects.create(
                    pedido=pedido,
                    cajero=request.user,
                    monto_total=pedido.total,
                    metodo_pago=metodo_pago,
                )
                venta_ids.append(str(venta.id))
            actualizar_estado_mesa(mesa)

        return JsonResponse({
            'success': True,
            'factura_url': f"/caja/factura/{'-'.join(venta_ids)}/",
        })
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'error': 'Datos de pago inválidos.'}, status=400)


@login_required(login_url='login')
def factura(request, venta_ids):
    ids = [int(item) for item in venta_ids.split('-') if item.isdigit()]
    ventas = list(Venta.objects.filter(id__in=ids).select_related('pedido__mesa', 'cajero').prefetch_related('pedido__detalles__producto'))
    if not ventas:
        messages.error(request, 'La factura no existe.')
        return redirect('dashboard')

    ventas.sort(key=lambda venta: ids.index(venta.id) if venta.id in ids else 0)
    subtotal = sum((venta.monto_total for venta in ventas), Decimal('0'))
    factura_data = {
        'numero': '-'.join(str(venta.id) for venta in ventas),
        'fecha': ventas[0].fecha_venta,
        'mesa': ventas[0].pedido.mesa.numero if ventas[0].pedido.mesa else '-',
        'cliente': ventas[0].pedido.notas or 'Cliente',
        'cajero': ventas[0].cajero.first_name or ventas[0].cajero.username if ventas[0].cajero else 'Caja',
        'metodo_pago': metodo_pago_display(ventas[0]),
        'subtotal_display': money_cop(subtotal),
        'total_display': money_cop(subtotal),
        'ventas': [
            {
                'pedido_numero': venta.pedido.numero,
                'items': [
                    {
                        'cantidad': item.cantidad,
                        'producto': item.producto.nombre if item.producto else 'Producto eliminado',
                        'subtotal_display': money_cop(item.subtotal),
                    }
                    for item in venta.pedido.detalles.all()
                ] + ([
                    {
                        'cantidad': 1,
                        'producto': 'Recargo de reserva',
                        'subtotal_display': money_cop(venta.pedido.reserva.recargo_reserva),
                    }
                ] if hasattr(venta.pedido, 'reserva') else []),
            }
            for venta in ventas
        ],
    }
    back_url = 'dashboard'
    back_label = 'Volver a caja'
    try:
        empleado = Empleado.objects.get(usuario=request.user)
        if empleado.rol.nombre == 'administrador':
            back_url = 'admin_ventas'
            back_label = 'Volver a facturas'
    except Empleado.DoesNotExist:
        pass

    return render(request, 'factura.html', {
        'title': 'Factura',
        'factura': factura_data,
        'back_url': back_url,
        'back_label': back_label,
    })


def cocina_dashboard(request):
    promote_reservation_orders()

    pedidos = Pedido.objects.filter(
        estado='en_preparacion',
        mesa__isnull=False,
    ).select_related('mesa').prefetch_related('detalles__producto').order_by('fecha_creacion')

    now = timezone.now()
    kitchen_orders = []
    for pedido in pedidos:
        minutes = max(0, int((now - pedido.fecha_creacion).total_seconds() // 60))
        kitchen_orders.append({
            'numero': pedido.numero,
            'mesa': pedido.mesa.numero if pedido.mesa else '',
            'cliente': pedido.notas or 'Cliente',
            'minutes': minutes,
            'urgent': minutes >= 20,
            'detalles': [
                {
                    'cantidad': detalle.cantidad,
                    'producto': detalle.producto.nombre if detalle.producto else 'Producto eliminado',
                }
                for detalle in pedido.detalles.all()
            ],
        })

    context = {
        'user': request.user,
        'title': 'Monitor de Cocina - Restaurant DeliBites',
        'orders': kitchen_orders,
        'orders_count': len(kitchen_orders),
        'now': now,
    }
    return render(request, 'cocina.html', context)


@login_required(login_url='login')
@require_http_methods(["POST"])
def guardar_pedido(request):
    """
    Guarda un pedido creado desde el panel del mesero.
    """
    try:
        data = json.loads(request.body)
        mesa_numero = data.get('mesa_numero')
        cliente = (data.get('cliente') or '').strip()
        items = data.get('items', [])

        if not mesa_numero:
            return JsonResponse({'success': False, 'error': 'Selecciona una mesa.'}, status=400)
        if not cliente:
            return JsonResponse({'success': False, 'error': 'Ingresa el nombre del cliente.'}, status=400)
        if not items:
            return JsonResponse({'success': False, 'error': 'Agrega al menos un producto.'}, status=400)

        mesa = Mesa.objects.get(numero=mesa_numero)
        producto_ids = [item.get('producto_id') for item in items]
        productos = {
            producto.id: producto
            for producto in Producto.objects.filter(id__in=producto_ids, disponible=True)
        }

        with transaction.atomic():
            pedido = Pedido.objects.create(
                cliente=request.user,
                mesa=mesa,
                estado='en_preparacion',
                notas=cliente,
                total=0,
            )

            total = 0
            for item in items:
                producto = productos.get(item.get('producto_id'))
                cantidad = int(item.get('cantidad') or 0)
                if not producto or cantidad <= 0:
                    continue

                subtotal = producto.precio * cantidad
                total += subtotal
                DetallePedido.objects.create(
                    pedido=pedido,
                    producto=producto,
                    cantidad=cantidad,
                    precio_unitario=producto.precio,
                    subtotal=subtotal,
                )

            if not pedido.detalles.exists():
                pedido.delete()
                return JsonResponse({'success': False, 'error': 'Los productos seleccionados no están disponibles.'}, status=400)

            pedido.total = total
            pedido.save(update_fields=['total'])
            mesa.estado_mesa = 'ocupada'
            mesa.save(update_fields=['estado_mesa'])

        return JsonResponse({'success': True, 'pedido': serialize_pedido(pedido)})
    except Mesa.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'La mesa no existe.'}, status=404)
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'error': 'Datos de pedido inválidos.'}, status=400)


@login_required(login_url='login')
@require_http_methods(["POST"])
def actualizar_estado_pedido(request, numero):
    try:
        data = json.loads(request.body or '{}')
        estado = data.get('estado')
        if estado not in ['en_preparacion', 'listo', 'entregado']:
            return JsonResponse({'success': False, 'error': 'Estado inválido.'}, status=400)

        pedido = Pedido.objects.select_related('mesa').get(numero=numero)
        pedido.estado = estado
        if estado == 'entregado':
            pedido.fecha_entrega = timezone.now()
        pedido.save(update_fields=['estado', 'fecha_entrega'])
        actualizar_estado_mesa(pedido.mesa)

        return JsonResponse({'success': True, 'pedido': serialize_pedido(pedido)})
    except Pedido.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'El pedido no existe.'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Datos inválidos.'}, status=400)


@login_required(login_url='login')
@require_http_methods(["POST"])
def eliminar_pedido(request, numero):
    try:
        pedido = Pedido.objects.select_related('mesa').get(numero=numero)
        mesa = pedido.mesa
        pedido.estado = 'cancelado'
        pedido.save(update_fields=['estado'])
        actualizar_estado_mesa(mesa)
        return JsonResponse({'success': True})
    except Pedido.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'El pedido no existe.'}, status=404)


def serialize_pedido(pedido):
    pedido = Pedido.objects.select_related('mesa').prefetch_related('detalles__producto').get(numero=pedido.numero)
    return {
        'numero': pedido.numero,
        'cliente': pedido.notas,
        'estado': pedido.estado,
        'estado_display': pedido.get_estado_display(),
        'hora': timezone.localtime(pedido.fecha_creacion).strftime('%I:%M %p').lower(),
        'total': float(pedido.total),
        'total_display': f'${pedido.total:,.0f}'.replace(',', '.'),
        'detalles': [
            {
                'producto': detalle.producto.nombre if detalle.producto else 'Producto eliminado',
                'cantidad': detalle.cantidad,
                'subtotal': float(detalle.subtotal),
                'subtotal_display': f'${detalle.subtotal:,.0f}'.replace(',', '.'),
            }
            for detalle in pedido.detalles.all()
        ],
    }


def actualizar_estado_mesa(mesa):
    if not mesa:
        return
    tiene_pedidos = pedidos_pendientes_pago_queryset().filter(mesa=mesa).exists()
    mesa.estado_mesa = 'ocupada' if tiene_pedidos else 'libre'
    mesa.save(update_fields=['estado_mesa'])


@login_required(login_url='login')
def estado_mesas(request):
    occupied_order_query = pedidos_pendientes_pago_queryset().filter(mesa=OuterRef('pk')).order_by('-fecha_creacion')
    mesas = Mesa.objects.filter(disponible=True).annotate(
        has_unpaid_order=Exists(occupied_order_query),
        titular_ocupada=Subquery(occupied_order_query.values('notas')[:1]),
    ).order_by('numero')

    return JsonResponse({
        'mesas': [
            {
                'id': mesa.id,
                'numero': mesa.numero,
                'estado': 'ocupada' if mesa.has_unpaid_order else mesa.estado_mesa,
                'titular': mesa.titular_ocupada or '',
            }
            for mesa in mesas
        ]
    })


@login_required(login_url='login')
def logout_view(request):
    """
    Vista para manejar el logout
    """
    storage = messages.get_messages(request)
    for _ in storage:
        pass
    storage.used = True
    logout(request)
    messages.success(request, 'Ha cerrado sesión correctamente.')
    return redirect('login')


@login_required(login_url='login')
def reservas(request):
    """
    Vista para que clientes reserven una mesa y pidan comida anticipada.
    """
    categorias = Categoria.objects.prefetch_related('producto_set').all()
    productos_menu = []
    for categoria in categorias:
        for producto in categoria.producto_set.filter(disponible=True).order_by('nombre'):
            productos_menu.append({
                'id': producto.id,
                'nombre': producto.nombre,
                'categoria': categoria.nombre,
                'precio': float(producto.precio),
                'precio_display': money_cop(producto.precio),
                'imagen_url': producto.imagen.url if producto.imagen else '',
            })

    if request.method == 'POST':
        try:
            reserva_id = request.POST.get('reserva_id')
            mesa = Mesa.objects.get(id=request.POST.get('mesa_id'), disponible=True)
            fecha_reserva = datetime.strptime(request.POST.get('fecha'), '%Y-%m-%d').date()
            hora_reserva = datetime.strptime(request.POST.get('hora'), '%H:%M').time()
            reserva_dt = timezone.make_aware(datetime.combine(fecha_reserva, hora_reserva))
            cantidad_personas = int(request.POST.get('personas') or 0)
            items = json.loads(request.POST.get('items_json') or '[]')

            if reserva_dt <= timezone.now():
                messages.error(request, 'La reserva debe ser para una fecha y hora futura.')
                return redirect('reservas')
            if hora_reserva < time(13, 0) or hora_reserva > time(21, 0):
                messages.error(request, 'Las reservas solo estan disponibles de 1:00 p. m. a 9:00 p. m.')
                return redirect('reservas')
            if cantidad_personas <= 0:
                messages.error(request, 'Ingresa la cantidad de personas.')
                return redirect('reservas')
            if cantidad_personas > mesa.capacidad:
                messages.error(request, f'La mesa {mesa.numero} tiene capacidad para {mesa.capacidad} persona(s).')
                return redirect('reservas')
            if not items:
                messages.error(request, 'Agrega al menos un producto para tu reserva.')
                return redirect('reservas')

            reserva = None
            if reserva_id:
                reserva = Reserva.objects.select_related('pedido').get(id=reserva_id, cliente=request.user)
                if not reserva.editable_hasta or timezone.now() > reserva.editable_hasta or reserva.pedido.estado != 'pendiente':
                    messages.error(request, 'La ventana de edición de 10 minutos ya terminó.')
                    return redirect('reservas')

            mesa_ocupada = pedidos_pendientes_pago_queryset().filter(mesa=mesa, reserva__isnull=True).exists()
            if mesa_ocupada and not (reserva and reserva.mesa_id == mesa.id):
                messages.error(request, f'La mesa {mesa.numero} esta ocupada en este momento.')
                return redirect('reservas')

            window_start, window_end = reservation_window_bounds(reserva_dt)
            conflicts = Reserva.objects.filter(
                mesa=mesa,
                fecha_reserva=fecha_reserva,
                hora_reserva__gt=(window_start - timedelta(hours=1)).time(),
                hora_reserva__lt=window_end.time(),
            ).exclude(estado='cancelada')
            if reserva:
                conflicts = conflicts.exclude(id=reserva.id)
            if conflicts.exists():
                messages.error(request, 'Esa mesa ya esta reservada en una franja que se cruza con esa hora. Cada reserva ocupa 1 hora.')
                return redirect('reservas')

            product_ids = [item.get('producto_id') for item in items]
            productos = {
                producto.id: producto
                for producto in Producto.objects.filter(id__in=product_ids, disponible=True)
            }

            with transaction.atomic():
                if reserva:
                    pedido = reserva.pedido
                    pedido.detalles.all().delete()
                else:
                    pedido = Pedido.objects.create(
                        cliente=request.user,
                        mesa=mesa,
                        estado='pendiente',
                        notas=request.user.first_name or request.user.username,
                        total=0,
                    )

                total_productos = Decimal('0')
                for item in items:
                    producto = productos.get(item.get('producto_id'))
                    cantidad = int(item.get('cantidad') or 0)
                    if not producto or cantidad <= 0:
                        continue
                    subtotal = producto.precio * cantidad
                    total_productos += subtotal
                    DetallePedido.objects.create(
                        pedido=pedido,
                        producto=producto,
                        cantidad=cantidad,
                        precio_unitario=producto.precio,
                        subtotal=subtotal,
                    )

                if not pedido.detalles.exists():
                    pedido.delete()
                    messages.error(request, 'Los productos seleccionados no están disponibles.')
                    return redirect('reservas')

                recargo = Decimal('10000')
                pedido.mesa = mesa
                pedido.total = total_productos + recargo
                pedido.notas = request.user.first_name or request.user.username
                pedido.save(update_fields=['mesa', 'total', 'notas'])

                if reserva:
                    reserva.mesa = mesa
                    reserva.pedido = pedido
                    reserva.nombre_cliente = request.POST.get('nombre') or request.user.first_name or request.user.username
                    reserva.email = request.POST.get('email') or request.user.email
                    reserva.telefono = request.POST.get('telefono') or ''
                    reserva.cantidad_personas = cantidad_personas
                    reserva.fecha_reserva = fecha_reserva
                    reserva.hora_reserva = hora_reserva
                    reserva.comentarios = request.POST.get('comentarios') or ''
                    reserva.recargo_reserva = recargo
                    reserva.save()
                    messages.success(request, 'Reserva actualizada correctamente.')
                else:
                    Reserva.objects.create(
                        cliente=request.user,
                        mesa=mesa,
                        pedido=pedido,
                        nombre_cliente=request.POST.get('nombre') or request.user.first_name or request.user.username,
                        email=request.POST.get('email') or request.user.email,
                        telefono=request.POST.get('telefono') or '',
                        cantidad_personas=cantidad_personas,
                        fecha_reserva=fecha_reserva,
                        hora_reserva=hora_reserva,
                        estado='pendiente',
                        recargo_reserva=recargo,
                        editable_hasta=timezone.now() + timedelta(minutes=10),
                        comentarios=request.POST.get('comentarios') or '',
                    )
                    messages.success(request, 'Reserva creada. Se agregó el recargo de reserva de $10.000.')
        except (Mesa.DoesNotExist, Reserva.DoesNotExist, ValueError, TypeError, json.JSONDecodeError):
            messages.error(request, 'No se pudo guardar la reserva. Revisa los datos e intenta de nuevo.')
        return redirect('reservas')

    reservas_cliente = Reserva.objects.select_related('mesa', 'pedido').prefetch_related('pedido__detalles__producto').filter(
        cliente=request.user
    ).order_by('-fecha_reserva', '-hora_reserva')
    occupied_order_query = pedidos_pendientes_pago_queryset().filter(mesa=OuterRef('pk')).order_by('-fecha_creacion')
    mesa_queryset = Mesa.objects.filter(disponible=True).annotate(
        has_unpaid_order=Exists(occupied_order_query),
        titular_ocupada=Subquery(occupied_order_query.values('notas')[:1]),
    ).order_by('numero')
    zonas = Zona.objects.prefetch_related(Prefetch('mesas_set', queryset=mesa_queryset)).all()
    mesas = mesa_queryset.select_related('zona').order_by('zona__nombre', 'numero')
    zonas_data = [
        {
            'id': zona.id,
            'x': zona.x,
            'y': zona.y,
            'width': zona.width,
            'height': zona.height,
            'shape': zona.shape,
        }
        for zona in zonas
    ]
    mesas_data = [
        {
            'id': mesa.id,
            'numero': mesa.numero,
            'capacidad': mesa.capacidad,
            'x': mesa.x,
            'y': mesa.y,
            'width': mesa.width,
            'height': mesa.height,
            'zonaId': mesa.zona_id,
            'estado': 'ocupada' if mesa.has_unpaid_order else mesa.estado_mesa,
            'titular': mesa.titular_ocupada or '',
        }
        for mesa in mesas
    ]
    reservas_data = []
    for reserva in reservas_cliente:
        puede_editar = (
            reserva.editable_hasta
            and timezone.now() <= reserva.editable_hasta
            and reserva.pedido
            and reserva.pedido.estado == 'pendiente'
        )
        reservas_data.append({
            'id': reserva.id,
            'mesa': reserva.mesa.numero if reserva.mesa else '-',
            'fecha': reserva.fecha_reserva,
            'hora': reserva.hora_reserva,
            'estado': reserva.get_estado_display(),
            'total_display': money_cop(reserva.pedido.total if reserva.pedido else 0),
            'puede_editar': puede_editar,
        })

    context = {
        'title': 'Reservar Mesa - Restaurant DeliBites',
        'mesas': mesas,
        'zonas': zonas,
        'zonas_json': json.dumps(zonas_data),
        'mesas_json': json.dumps(mesas_data),
        'productos_menu_json': json.dumps(productos_menu),
        'reservas_cliente': reservas_data,
        'recargo_reserva_display': money_cop(10000),
        'default_nombre': request.user.first_name or request.user.username,
        'default_email': request.user.email,
        'now': timezone.now(),
    }
    return render(request, 'reservas.html', context)


def get_stats_by_period(period='dia'):
    """
    Obtiene estadísticas filtradas por período (día, semana, mes)
    """
    from collections import defaultdict
    now = timezone.now()
    
    if period == 'dia':
        start_date = now.date()
    elif period == 'semana':
        start_date = (now.date() - timedelta(days=now.weekday()))
    elif period == 'mes':
        start_date = now.date().replace(day=1)
    else:
        start_date = now.date()
    
    # Productos más vendidos
    productos_vendidos = DetallePedido.objects.filter(
        pedido__fecha_creacion__date__gte=start_date,
        pedido__estado__in=['entregado', 'listo']
    ).values('producto__nombre').annotate(
        cantidad=Sum('cantidad')
    ).order_by('-cantidad')[:10]
    
    top_productos = {
        'labels': [p['producto__nombre'] or 'Producto eliminado' for p in productos_vendidos],
        'data': [int(p['cantidad'] or 0) for p in productos_vendidos]
    }
    
    # Ventas por período
    ventas_dict = defaultdict(float)
    
    if period == 'dia':
        # Ventas por hora
        ventas_por_periodo = Venta.objects.filter(
            fecha_venta__date=start_date
        ).annotate(hora=TruncHour('fecha_venta')).values('hora').annotate(
            total=Sum('monto_total')
        ).order_by('hora')
        
        for v in ventas_por_periodo:
            if v['hora']:
                hora = timezone.localtime(v['hora']).strftime('%H:00')
                ventas_dict[hora] = float(v['total'] or 0)
        
        # Llenar horas vacías
        for i in range(24):
            hora_key = f"{i:02d}:00"
            if hora_key not in ventas_dict:
                ventas_dict[hora_key] = 0.0
    else:
        # Ventas por día
        ventas_por_periodo = Venta.objects.filter(
            fecha_venta__date__gte=start_date
        ).annotate(fecha=TruncDate('fecha_venta')).values('fecha').annotate(
            total=Sum('monto_total')
        ).order_by('fecha')
        
        for v in ventas_por_periodo:
            if v['fecha']:
                fecha_key = v['fecha'].strftime('%d/%m')
                ventas_dict[fecha_key] = float(v['total'] or 0)
    
    labels = sorted(ventas_dict.keys()) if period == 'dia' else list(ventas_dict.keys())
    
    ventas_chart = {
        'labels': labels,
        'data': [ventas_dict.get(label, 0) for label in labels]
    }
    
    # Empleados con más mesas atendidas
    empleados_mesas = Pedido.objects.filter(
        fecha_creacion__date__gte=start_date,
        mesa__isnull=False
    ).values('cliente__first_name').annotate(
        mesas=Count('mesa', distinct=True)
    ).order_by('-mesas')[:10]
    
    empleados_chart = {
        'labels': [e['cliente__first_name'] or 'Desconocido' for e in empleados_mesas],
        'data': [int(e['mesas'] or 0) for e in empleados_mesas]
    }
    
    # Ventas por categoría
    ventas_categoria = DetallePedido.objects.filter(
        pedido__fecha_creacion__date__gte=start_date,
        pedido__estado__in=['entregado', 'listo']
    ).values('producto__categoria__nombre').annotate(
        cantidad=Sum('cantidad'),
        total=Sum('subtotal')
    ).order_by('-total')
    
    categoria_chart = {
        'labels': [v['producto__categoria__nombre'] or 'Sin categoría' for v in ventas_categoria],
        'data': [float(v['total'] or 0) for v in ventas_categoria]
    }
    
    return {
        'top_productos': top_productos,
        'ventas': ventas_chart,
        'empleados': empleados_chart,
        'categorias': categoria_chart
    }


@login_required(login_url='login')
def admin_panel(request):
    """
    Vista del panel de administración con gráficas estadísticas
    """
    # Verificar que sea administrador
    try:
        empleado = Empleado.objects.get(usuario=request.user)
        if empleado.rol.nombre != 'administrador':
            messages.error(request, 'No tienes permisos para acceder al panel de administración.')
            return redirect('dashboard')
    except Empleado.DoesNotExist:
        messages.error(request, 'No tienes permisos para acceder al panel de administración.')
        return redirect('dashboard')
    
    # Obtener período seleccionado
    period = request.GET.get('period', 'dia')
    if period not in ['dia', 'semana', 'mes']:
        period = 'dia'
    
    # Obtener estadísticas
    stats = get_stats_by_period(period)
    
    # Obtener totales del período
    now = timezone.now()
    if period == 'dia':
        start_date = now.date()
    elif period == 'semana':
        start_date = (now.date() - timedelta(days=now.weekday()))
    elif period == 'mes':
        start_date = now.date().replace(day=1)
    else:
        start_date = now.date()
    
    ventas_periodo = Venta.objects.filter(fecha_venta__date__gte=start_date)
    total_ventas = ventas_periodo.aggregate(Sum('monto_total'))['monto_total__sum'] or 0
    total_pedidos = Pedido.objects.filter(fecha_creacion__date__gte=start_date).count()
    
    context = {
        'user': request.user,
        'title': 'Panel de Administración',
        'period': period,
        'total_ventas': money_cop(total_ventas),
        'total_pedidos': total_pedidos,
        'periodo_label': {'dia': 'Hoy', 'semana': 'Esta Semana', 'mes': 'Este Mes'}[period],
        'top_productos_json': json.dumps(stats['top_productos']),
        'ventas_json': json.dumps(stats['ventas']),
        'empleados_json': json.dumps(stats['empleados']),
        'categorias_json': json.dumps(stats['categorias']),
    }
    
    return render(request, 'admin/panel.html', context)


@login_required(login_url='login')
def admin_ventas(request):
    """
    Vista de ventas del panel admin
    """
    try:
        empleado = Empleado.objects.get(usuario=request.user)
        if empleado.rol.nombre != 'administrador':
            messages.error(request, 'No tienes permisos para acceder al panel de administración.')
            return redirect('dashboard')
    except Empleado.DoesNotExist:
        messages.error(request, 'No tienes permisos para acceder al panel de administración.')
        return redirect('dashboard')
    
    ventas = Venta.objects.select_related('pedido__mesa', 'pedido', 'cajero').order_by('-fecha_venta')[:50]
    total_ventas = Venta.objects.aggregate(Sum('monto_total'))['monto_total__sum'] or 0
    ventas_data = [
        {
            'id': venta.id,
            'fecha_venta': venta.fecha_venta,
            'mesa': venta.pedido.mesa.numero if venta.pedido.mesa else None,
            'cliente': venta.pedido.notas or 'Cliente',
            'items': venta.pedido.detalles.count(),
            'metodo_pago': metodo_pago_display(venta),
            'monto_total': money_cop(venta.monto_total),
            'detalle_url': f"/caja/factura/{venta.id}/",
        }
        for venta in ventas
    ]
    
    context = {
        'title': 'Facturas',
        'ventas': ventas_data,
        'total_ventas': money_cop(total_ventas),
    }
    
    return render(request, 'admin/ventas.html', context)


@login_required(login_url='login')
def admin_empleados(request):
    """
    Vista de empleados del panel admin
    """
    try:
        empleado = Empleado.objects.get(usuario=request.user)
        if empleado.rol.nombre != 'administrador':
            messages.error(request, 'No tienes permisos para acceder al panel de administración.')
            return redirect('dashboard')
    except Empleado.DoesNotExist:
        messages.error(request, 'No tienes permisos para acceder al panel de administración.')
        return redirect('dashboard')
    
    empleados = Empleado.objects.all().select_related('usuario', 'rol')
    
    context = {
        'title': 'Empleados',
        'empleados': empleados,
    }
    
    return render(request, 'admin/empleados.html', context)


@login_required(login_url='login')
def admin_menu(request):
    """
    Vista del menú del panel admin
    """
    try:
        empleado = Empleado.objects.get(usuario=request.user)
        if empleado.rol.nombre != 'administrador':
            messages.error(request, 'No tienes permisos para acceder al panel de administración.')
            return redirect('dashboard')
    except Empleado.DoesNotExist:
        messages.error(request, 'No tienes permisos para acceder al panel de administración.')
        return redirect('dashboard')
    
    categorias = list(Categoria.objects.prefetch_related('producto_set'))
    for categoria in categorias:
        for producto in categoria.producto_set.all():
            producto.precio_display = money_cop(producto.precio)
    productos = Producto.objects.all()
    
    context = {
        'title': 'Menú',
        'categorias': categorias,
        'productos': productos,
    }
    
    return render(request, 'admin/menu.html', context)


@login_required(login_url='login')
def admin_zonas(request):
    """
    Vista de zonas del panel admin
    """
    try:
        empleado = Empleado.objects.get(usuario=request.user)
        if empleado.rol.nombre != 'administrador':
            messages.error(request, 'No tienes permisos para acceder al panel de administración.')
            return redirect('dashboard')
    except Empleado.DoesNotExist:
        messages.error(request, 'No tienes permisos para acceder al panel de administración.')
        return redirect('dashboard')
    
    zonas = Zona.objects.prefetch_related('mesas_set')
    
    # Convertir zonas a JSON para el canvas
    import json
    zonas_data = []
    for zona in zonas:
        zonas_data.append({
            'id': zona.id,
            'nombre': zona.nombre,
            'color': zona.color,
            'x': zona.x,
            'y': zona.y,
            'width': zona.width,
            'height': zona.height,
            'shape': zona.shape,
            'mesas_count': zona.mesas_set.count()
        })
    
    context = {
        'title': 'Zonas',
        'zonas': zonas,
        'zonas_json': json.dumps(zonas_data),
    }
    
    return render(request, 'admin/zonas.html', context)


@login_required(login_url='login')
@require_http_methods(["POST"])
def guardar_zonas(request):
    """
    Endpoint para guardar cambios en las zonas
    """
    try:
        empleado = Empleado.objects.get(usuario=request.user)
        if empleado.rol.nombre != 'administrador':
            return JsonResponse({'error': 'No tienes permisos'}, status=403)
    except Empleado.DoesNotExist:
        return JsonResponse({'error': 'No tienes permisos'}, status=403)
    
    try:
        data = json.loads(request.body)
        zonas_data = data.get('zonas', [])
        
        # Log para debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Recibidas {len(zonas_data)} zonas para actualizar/crear")
        
        submitted_existing_ids = {
            zona_data.get('id')
            for zona_data in zonas_data
            if zona_data.get('id') and zona_data.get('id') > 0
        }

        # Eliminar zonas que el usuario quitó antes de guardar, junto con sus mesas.
        zones_to_delete = Zona.objects.exclude(id__in=submitted_existing_ids)
        deleted_zone_ids = list(zones_to_delete.values_list('id', flat=True))
        deleted_mesas_count = Mesa.objects.filter(zona_id__in=deleted_zone_ids).delete()[0]
        deleted_count = zones_to_delete.delete()[0]

        # Actualizar o crear cada zona
        updated_count = 0
        reset_mesas_count = 0
        valid_shapes = {'rectangle', 'l-shape', 'triangle', 'hexagon'}
        for zona_data in zonas_data:
            try:
                zona_id = zona_data.get('id')
                
                # Verificar si es una zona existente o nueva
                # ID = 0 significa que es una zona nueva no guardada aún
                if zona_id and zona_id > 0:
                    # Actualizar zona existente
                    try:
                        zona = Zona.objects.get(id=zona_id)
                    except Zona.DoesNotExist:
                        logger.warning(f"Zona con id {zona_id} no encontrada; se omite para evitar duplicados")
                        continue
                else:
                    # Crear nueva zona
                    zona = Zona()
                
                zona.nombre = zona_data.get('nombre', 'Nueva Zona')
                zona.color = zona_data.get('color', '#FF0000')
                zona.x = zona_data.get('x', 0)
                zona.y = zona_data.get('y', 0)
                zona.width = zona_data.get('width', 200)
                zona.height = zona_data.get('height', 150)
                zona.shape = zona_data.get('shape', 'rectangle')
                if zona.shape not in valid_shapes:
                    zona.shape = 'rectangle'
                
                zona.save()

                if zona_data.get('reset_mesas'):
                    reset_mesas_count += Mesa.objects.filter(zona=zona).delete()[0]

                updated_count += 1
                logger.info(f"Zona '{zona.nombre}' (id={zona.id}) guardada exitosamente")
            except Zona.DoesNotExist:
                logger.error(f"Zona con id {zona_data.get('id')} no encontrada")
            except Exception as e:
                logger.error(f"Error al guardar zona: {str(e)}")
        
        return JsonResponse({
            'success': True,
            'message': f'{updated_count} zona(s) guardada(s), {deleted_count} eliminada(s), {reset_mesas_count + deleted_mesas_count} mesa(s) borrada(s)',
            'updated': updated_count,
            'deleted': deleted_count,
            'deleted_mesas': reset_mesas_count + deleted_mesas_count
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error al guardar zonas: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required(login_url='login')
def admin_mesas(request):
    """
    Vista de disposición de mesas del panel admin
    """
    try:
        empleado = Empleado.objects.get(usuario=request.user)
        if empleado.rol.nombre != 'administrador':
            messages.error(request, 'No tienes permisos para acceder al panel de administración.')
            return redirect('dashboard')
    except Empleado.DoesNotExist:
        messages.error(request, 'No tienes permisos para acceder al panel de administración.')
        return redirect('dashboard')
    
    import json
    
    # Obtener zonas y mesas
    zonas = Zona.objects.all()
    mesas = Mesa.objects.all()
    
    # Convertir a JSON
    zonas_data = []
    for zona in zonas:
        zonas_data.append({
            'id': zona.id,
            'nombre': zona.nombre,
            'color': zona.color,
            'x': zona.x,
            'y': zona.y,
            'width': zona.width,
            'height': zona.height,
            'shape': zona.shape,
        })
    
    mesas_data = []
    for mesa in mesas:
        mesas_data.append({
            'id': mesa.id,
            'numero': mesa.numero,
            'capacidad': mesa.capacidad,
            'x': mesa.x,
            'y': mesa.y,
            'width': mesa.width,
            'height': mesa.height,
            'zona_id': mesa.zona_id,
            'estado': mesa.estado_mesa,
        })
    
    zonas_json = json.dumps(zonas_data)
    mesas_json = json.dumps(mesas_data)
    
    context = {
        'title': 'Disposición de Mesas',
        'zonas': zonas,
        'mesas': mesas,
        'zonas_json': zonas_json,
        'mesas_json': mesas_json,
    }
    
    return render(request, 'admin/mesas.html', context)


@login_required
@require_http_methods(["POST"])
def guardar_mesas(request):
    """
    Endpoint para guardar cambios en la disposicion de mesas.
    Actualiza mesas existentes y crea las mesas nuevas enviadas desde el editor.
    """
    try:
        empleado = Empleado.objects.get(usuario=request.user)
        if empleado.rol.nombre != 'administrador':
            return JsonResponse({'error': 'No tienes permisos'}, status=403)
    except Empleado.DoesNotExist:
        return JsonResponse({'error': 'No tienes permisos'}, status=403)
    
    try:
        data = json.loads(request.body)
        mesas_data = data.get('mesas', [])
        
        # Log para debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Recibidas {len(mesas_data)} mesas para actualizar/crear")
        
        # Actualizar cada mesa
        updated_count = 0
        created_count = 0
        saved_mesas = []

        def parse_int(value, field_name, default=None):
            if value in (None, ''):
                return default
            try:
                return int(value)
            except (TypeError, ValueError):
                raise ValidationError(f'El campo {field_name} debe ser un numero valido.')

        zona_ids = {
            parse_int(mesa_data.get('zona_id'), 'zona')
            for mesa_data in mesas_data
            if mesa_data.get('zona_id')
        }
        zonas_existentes = set(Zona.objects.filter(id__in=zona_ids).values_list('id', flat=True))
        for mesa_data in mesas_data:
            mesa_id = parse_int(mesa_data.get('id'), 'id')
            numero = parse_int(mesa_data.get('numero'), 'numero de mesa')
            capacidad = parse_int(mesa_data.get('capacidad'), 'capacidad', 4)
            zona_id = parse_int(mesa_data.get('zona_id'), 'zona', None)

            if not numero or numero <= 0:
                return JsonResponse({'error': 'Cada mesa debe tener un numero mayor a cero.'}, status=400)
            if capacidad <= 0:
                return JsonResponse({'error': f'La capacidad de la mesa {numero} debe ser mayor a cero.'}, status=400)
            if zona_id and zona_id not in zonas_existentes:
                return JsonResponse({'error': f'La zona seleccionada para la mesa {numero} no existe.'}, status=400)

            try:
                mesa = Mesa.objects.filter(id=mesa_id).first() if mesa_id and mesa_id > 0 else None
                if mesa is None:
                    mesa = Mesa()
                old_x, old_y = mesa.x, mesa.y
                is_new = mesa.pk is None

                duplicate_query = Mesa.objects.filter(numero=numero)
                if mesa.pk:
                    duplicate_query = duplicate_query.exclude(pk=mesa.pk)
                if duplicate_query.exists():
                    return JsonResponse({'error': f'Ya existe una mesa con el numero {numero}.'}, status=400)
                
                mesa.x = parse_int(mesa_data.get('x'), 'x', mesa.x)
                mesa.y = parse_int(mesa_data.get('y'), 'y', mesa.y)
                mesa.width = parse_int(mesa_data.get('width'), 'ancho', mesa.width)
                mesa.height = parse_int(mesa_data.get('height'), 'alto', mesa.height)
                mesa.numero = numero
                mesa.capacidad = capacidad
                mesa.estado_mesa = mesa_data.get('estado') or mesa.estado_mesa
                
                mesa.zona_id = zona_id
                
                mesa.save()
                if is_new:
                    created_count += 1
                    logger.info(f"Mesa {mesa.numero} creada en ({mesa.x}, {mesa.y})")
                else:
                    updated_count += 1
                    logger.info(f"Mesa {mesa.numero} actualizada: ({old_x}, {old_y}) -> ({mesa.x}, {mesa.y})")

                saved_mesas.append({
                    'temp_id': mesa_id,
                    'id': mesa.id,
                    'numero': mesa.numero,
                })
            except Mesa.DoesNotExist:
                logger.warning(f"Mesa con ID {mesa_id} no encontrada")
                continue
        
        return JsonResponse({
            'success': True,
            'message': f'Cambios guardados correctamente ({updated_count} actualizada(s), {created_count} creada(s))',
            'updated': updated_count,
            'created': created_count,
            'mesas': saved_mesas,
        })
    
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalido'}, status=400)
    except ValidationError as e:
        return JsonResponse({'error': e.messages[0] if e.messages else str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ======================== VISTAS DE EMPLEADOS ========================

@login_required(login_url='login')
def admin_empleado_crear(request):
    """
    Vista para crear un nuevo empleado
    """
    try:
        empleado = Empleado.objects.get(usuario=request.user)
        if empleado.rol.nombre != 'administrador':
            messages.error(request, 'No tienes permisos para esta acción.')
            return redirect('admin_panel')
    except Empleado.DoesNotExist:
        messages.error(request, 'No tienes permisos para esta acción.')
        return redirect('admin_panel')
    
    if request.method == 'POST':
        form = EmpleadoForm(request.POST)
        if form.is_valid():
            try:
                # Crear el usuario
                username = form.cleaned_data['username']
                email = form.cleaned_data['email']
                first_name = form.cleaned_data['first_name']
                password = form.cleaned_data.get('password')
                
                # Verificar que el usuario no exista
                if User.objects.filter(username=username).exists():
                    messages.error(request, 'El usuario ya existe.')
                    return render(request, 'admin/empleado_form.html', {'form': form, 'title': 'Crear Empleado'})
                
                # Crear usuario
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    first_name=first_name,
                    password=password or 'TempPassword123'
                )
                
                # Crear empleado
                empleado_nuevo = form.save(commit=False)
                empleado_nuevo.usuario = user
                empleado_nuevo.save()
                
                messages.success(request, f'Empleado "{first_name}" creado exitosamente.')
                return redirect('admin_empleados')
            except Exception as e:
                messages.error(request, f'Error al crear el empleado: {str(e)}')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = EmpleadoForm()
    
    context = {
        'form': form,
        'title': 'Crear Empleado',
    }
    return render(request, 'admin/empleado_form.html', context)


@login_required(login_url='login')
def admin_empleado_editar(request, id):
    """
    Vista para editar un empleado
    """
    try:
        empleado = Empleado.objects.get(usuario=request.user)
        if empleado.rol.nombre != 'administrador':
            messages.error(request, 'No tienes permisos para esta acción.')
            return redirect('admin_panel')
    except Empleado.DoesNotExist:
        messages.error(request, 'No tienes permisos para esta acción.')
        return redirect('admin_panel')
    
    try:
        empleado_editar = Empleado.objects.get(id=id)
    except Empleado.DoesNotExist:
        messages.error(request, 'El empleado no existe.')
        return redirect('admin_empleados')
    
    if request.method == 'POST':
        form = EmpleadoForm(request.POST, instance=empleado_editar)
        if form.is_valid():
            try:
                # Actualizar usuario
                user = empleado_editar.usuario
                user.first_name = form.cleaned_data['first_name']
                user.email = form.cleaned_data['email']
                user.username = form.cleaned_data['username']
                
                if form.cleaned_data.get('password'):
                    user.set_password(form.cleaned_data['password'])
                
                user.save()
                
                # Guardar empleado
                form.save()
                
                messages.success(request, 'Empleado actualizado exitosamente.')
                return redirect('admin_empleados')
            except Exception as e:
                messages.error(request, f'Error al actualizar el empleado: {str(e)}')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = EmpleadoForm(instance=empleado_editar)
        form.initial['first_name'] = empleado_editar.usuario.first_name
        form.initial['email'] = empleado_editar.usuario.email
        form.initial['username'] = empleado_editar.usuario.username
    
    context = {
        'form': form,
        'title': f'Editar Empleado - {empleado_editar.usuario.first_name}',
        'empleado_id': id,
    }
    return render(request, 'admin/empleado_form.html', context)


@login_required(login_url='login')
@require_http_methods(["POST"])
def admin_empleado_eliminar(request, id):
    """
    Vista para eliminar un empleado
    """
    try:
        empleado = Empleado.objects.get(usuario=request.user)
        if empleado.rol.nombre != 'administrador':
            return JsonResponse({'error': 'No tienes permisos'}, status=403)
    except Empleado.DoesNotExist:
        return JsonResponse({'error': 'No tienes permisos'}, status=403)
    
    try:
        empleado_eliminar = Empleado.objects.get(id=id)
        nombre = empleado_eliminar.usuario.first_name
        usuario = empleado_eliminar.usuario
        
        # Eliminar empleado y usuario
        empleado_eliminar.delete()
        usuario.delete()
        
        messages.success(request, f'Empleado "{nombre}" eliminado exitosamente.')
        return redirect('admin_empleados')
    except Empleado.DoesNotExist:
        messages.error(request, 'El empleado no existe.')
        return redirect('admin_empleados')
    except Exception as e:
        messages.error(request, f'Error al eliminar el empleado: {str(e)}')
        return redirect('admin_empleados')


# ======================== VISTAS DE PRODUCTOS ========================

@login_required(login_url='login')
def admin_producto_crear(request):
    """
    Vista para crear un nuevo producto
    """
    try:
        empleado = Empleado.objects.get(usuario=request.user)
        if empleado.rol.nombre != 'administrador':
            messages.error(request, 'No tienes permisos para esta acción.')
            return redirect('admin_panel')
    except Empleado.DoesNotExist:
        messages.error(request, 'No tienes permisos para esta acción.')
        return redirect('admin_panel')
    
    if request.method == 'POST':
        form = ProductoForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, f'Producto "{form.cleaned_data["nombre"]}" creado exitosamente.')
                return redirect('admin_menu')
            except Exception as e:
                messages.error(request, f'Error al crear el producto: {str(e)}')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = ProductoForm()
    
    context = {
        'form': form,
        'title': 'Crear Producto',
    }
    return render(request, 'admin/producto_form.html', context)


@login_required(login_url='login')
def admin_producto_editar(request, id):
    """
    Vista para editar un producto
    """
    try:
        empleado = Empleado.objects.get(usuario=request.user)
        if empleado.rol.nombre != 'administrador':
            messages.error(request, 'No tienes permisos para esta acción.')
            return redirect('admin_panel')
    except Empleado.DoesNotExist:
        messages.error(request, 'No tienes permisos para esta acción.')
        return redirect('admin_panel')
    
    try:
        producto = Producto.objects.get(id=id)
    except Producto.DoesNotExist:
        messages.error(request, 'El producto no existe.')
        return redirect('admin_menu')
    
    if request.method == 'POST':
        form = ProductoForm(request.POST, request.FILES, instance=producto)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, 'Producto actualizado exitosamente.')
                return redirect('admin_menu')
            except Exception as e:
                messages.error(request, f'Error al actualizar el producto: {str(e)}')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = ProductoForm(instance=producto)
    
    context = {
        'form': form,
        'title': f'Editar Producto - {producto.nombre}',
        'producto_id': id,
    }
    return render(request, 'admin/producto_form.html', context)


@login_required(login_url='login')
@require_http_methods(["POST"])
def admin_producto_eliminar(request, id):
    """
    Vista para eliminar un producto
    """
    try:
        empleado = Empleado.objects.get(usuario=request.user)
        if empleado.rol.nombre != 'administrador':
            return JsonResponse({'error': 'No tienes permisos'}, status=403)
    except Empleado.DoesNotExist:
        return JsonResponse({'error': 'No tienes permisos'}, status=403)
    
    try:
        producto = Producto.objects.get(id=id)
        nombre = producto.nombre
        producto.delete()
        
        messages.success(request, f'Producto "{nombre}" eliminado exitosamente.')
        return redirect('admin_menu')
    except Producto.DoesNotExist:
        messages.error(request, 'El producto no existe.')
        return redirect('admin_menu')
    except Exception as e:
        messages.error(request, f'Error al eliminar el producto: {str(e)}')
        return redirect('admin_menu')


