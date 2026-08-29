import random
from django.contrib.auth import authenticate, login, logout
from django.core.mail import send_mail
from django.conf import settings
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.models import User

def custom_login_view(request):
    if request.user.is_authenticated:
        return redirect('inventario:dashboard')
        
    if request.method == 'POST':
        u = request.POST.get('username')
        p = request.POST.get('password')
        user = authenticate(request, username=u, password=p)
        if user is not None:
            # Login user directly
            login(request, user)
            return redirect('inventario:dashboard')
        else:
            messages.error(request, "Usuario o contraseña incorrectos.")
            
    return render(request, 'inventario/login.html')

def custom_logout_view(request):
    logout(request)
    return redirect('inventario:login')
