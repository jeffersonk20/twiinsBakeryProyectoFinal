# Desplegar en Render

El archivo `render.yaml` crea dos servicios web independientes:

- `twiins-bakery-clientes`: tienda de clientes.
- `twiins-bakery-admin`: panel administrativo.

Cada servicio recibe su propia dirección pública de Render. La tienda no
muestra enlaces de administración y sus rutas administrativas responden 404.
Los callbacks de pago usan la dirección pública de la tienda.

## Pasos

1. Sube este repositorio a GitHub y crea un Blueprint en Render seleccionando
   el repositorio y `render.yaml`.
2. En el primer despliegue, proporciona los valores de las variables que
   Render marca como secretas (`sync: false`).
3. En ambos servicios configura las credenciales de la misma base de datos
   MySQL remota. Render necesita poder conectarse a esa base desde fuera.
4. En el servicio `twiins-bakery-admin`, define `ADMIN_SETUP_TOKEN` con un
   valor aleatorio secreto de al menos 32 caracteres.
5. En el servicio `twiins-bakery-clientes`, define las credenciales Wompi.
6. Espera a que ambos servicios terminen su primer despliegue. Render asignará
   a cada servicio una URL distinta con el dominio `onrender.com`.
7. Abre la URL del servicio de administración para crear la cuenta inicial.

En modo local la aplicación conserva el comportamiento combinado. En Render,
las rutas de administración solo responden en el servicio administrativo y
las rutas de la tienda solo responden en el servicio de clientes.
