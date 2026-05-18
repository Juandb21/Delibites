from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from .models import Empleado, Producto, Rol


class CustomAuthenticationForm(AuthenticationForm):
    """Formulario personalizado de autenticación"""
    
    username = forms.CharField(
        label='Usuario',
        max_length=254,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ingrese su usuario',
            'autocomplete': 'username',
        })
    )
    
    password = forms.CharField(
        label='Contraseña',
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ingrese su contraseña',
            'autocomplete': 'current-password',
        })
    )

    class Meta:
        model = User
        fields = ('username', 'password')

    def clean(self):
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')

        if username and password:
            self.user_cache = None
            user = User.objects.filter(username=username).first()
            
            if user is None:
                raise ValidationError('El usuario no existe.')
            
            if not user.is_active:
                raise ValidationError('La cuenta está desactivada.')

            if not user.check_password(password):
                raise ValidationError('La contraseña es incorrecta.')
            
            self.user_cache = user
        
        return self.cleaned_data

    def get_user(self):
        return self.user_cache


class RegistroClienteForm(forms.ModelForm):
    """Formulario de registro para clientes"""
    
    password = forms.CharField(
        label='Contraseña',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Cree una contraseña',
        })
    )
    
    password_confirm = forms.CharField(
        label='Confirmar Contraseña',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirme su contraseña',
        })
    )
    
    class Meta:
        model = User
        fields = ('first_name', 'email', 'username')
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Tu nombre completo',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Tu correo electrónico',
            }),
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Crea un usuario',
            }),
        }
        labels = {
            'first_name': 'Nombre Completo',
            'email': 'Correo Electrónico',
            'username': 'Usuario',
        }


class EmpleadoForm(forms.ModelForm):
    """Formulario para crear/editar empleados"""
    
    first_name = forms.CharField(
        label='Nombre',
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nombre del empleado',
        })
    )
    
    email = forms.EmailField(
        label='Correo Electrónico',
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'correo@ejemplo.com',
        }),
        required=False
    )
    
    username = forms.CharField(
        label='Usuario',
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Usuario único',
        })
    )
    
    password = forms.CharField(
        label='Contraseña',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': '',
        }),
        required=False
    )
    
    class Meta:
        model = Empleado
        fields = ('rol', 'telefono')
        widgets = {
            'rol': forms.Select(attrs={
                'class': 'form-control',
            }),
            'telefono': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Teléfono',
            }),
        }
        labels = {
            'rol': 'Rol',
            'telefono': 'Teléfono',
        }


class ProductoForm(forms.ModelForm):
    """Formulario para crear/editar productos"""
    
    class Meta:
        model = Producto
        fields = ('nombre', 'categoria', 'precio', 'descripcion', 'imagen', 'disponible')
        widgets = {
            'nombre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre del producto',
            }),
            'categoria': forms.Select(attrs={
                'class': 'form-control',
            }),
            'precio': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: 20000',
                'step': '1',
                'min': '0',
            }),
            'descripcion': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Descripción (opcional)',
                'rows': 3,
            }),
            'imagen': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
            }),
            'disponible': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
        }
        labels = {
            'nombre': 'Nombre',
            'categoria': 'Categoría',
            'precio': 'Precio (COP)',
            'descripcion': 'Descripción',
            'imagen': 'Imagen del Producto',
            'disponible': 'Disponible',
        }

