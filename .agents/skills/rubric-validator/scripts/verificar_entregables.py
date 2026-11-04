#!/usr/bin/env python3
"""
Script de auditoria de entregables y cumplimiento de rubrica.
Comprueba la presencia y validez de todos los artefactos obligatorios.
"""

import os
import sys
from pathlib import Path

# Ajustar salida a UTF-8 para evitar errores con caracteres en consolas Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Raiz del proyecto buscando el directorio que contiene .git o README.md
current = Path(__file__).resolve()
PROJECT_ROOT = None
for p in [current] + list(current.parents):
    if (p / ".git").exists() and p.name == "Proyecto-actividad-sismica":
        PROJECT_ROOT = p
        break

if not PROJECT_ROOT:
    # Fallback
    PROJECT_ROOT = current.parents[3]

ENTREGABLES = [
    {
        "categoria": "Infraestructura Docker",
        "archivos": [
            ("compose.yaml", "Archivo Docker Compose con los 5 servicios"),
            ("Dockerfile.python", "Dockerfile reproducible para servicios Python"),
            (".env.example", "Plantilla de variables de entorno sin secretos"),
            (".gitignore", "Exclusion de node_modules, .env, caches y datos pesados"),
        ],
    },
    {
        "categoria": "Capa de Datos (SQL)",
        "archivos": [
            ("sql/01_init.sql", "Esquema DDL con 6 tablas, vistas e indices"),
            ("sql/02_seed_paises.sql", "Semillero de los 177 paises de Natural Earth"),
            ("sql/README.md", "Documentacion del modelo conceptual, logico y fisico"),
        ],
    },
    {
        "categoria": "Backend Python",
        "archivos": [
            ("backend/common/config.py", "Configuracion centralizada y tipada"),
            ("backend/producer/producer.py", "Extractor USGS y publicador Kafka"),
            ("backend/consumer/consumer.py", "Consumidor con validacion y escritura idempotente"),
            ("backend/consumer/spatial.py", "Enriquecimiento espacial Point-in-Polygon (STRtree)"),
            ("backend/api/main.py", "API FastAPI con /api/salud, /api/eventos, /api/estadisticas"),
            ("requirements.txt", "Dependencias fijadas de Python"),
        ],
    },
    {
        "categoria": "Frontend Angular + Leaflet",
        "archivos": [
            ("frontend/package.json", "Dependencias del frontend"),
            ("frontend/public/config.json", "Configuracion de conexion API/Demo"),
            ("frontend/public/datos/paises.geojson", "Catalogo cartografico de fronteras"),
            ("frontend/src/app/app.component.ts", "Logica del componente principal"),
            ("frontend/netlify.toml", "Configuracion de despliegue en Netlify"),
        ],
    },
    {
        "categoria": "Scripts de Validacion y Reproduccion",
        "archivos": [
            ("scripts/descargar_historico.py", "Descarga particionada del catalogo 2025"),
            ("scripts/reproducir_historico.py", "Replay acelerado con casos controlados"),
            ("scripts/probar_aceptacion.py", "Bateria automatizada de las 11 pruebas de aceptacion"),
            ("scripts/medir_rendimiento.py", "Benchmarks de complejidad Big-O y memoria RAM"),
        ],
    },
    {
        "categoria": "Documentacion y Memoria Academica",
        "archivos": [
            ("docs/memoria.md", "Memoria tecnica completa con las 6 dimensiones de calidad"),
            ("docs/evidencias/mediciones_rendimiento.md", "Evidencias empiricas de benchmarks"),
            ("README.md", "Guia paso a paso de puesta en marcha"),
        ],
    },
]

def verificar():
    print("=" * 75)
    print(" AUDITORIA DE ENTREGABLES DEL PROYECTO (OBSERVATORIO SISMICO)")
    print(f" Raiz evaluada: {PROJECT_ROOT}")
    print("=" * 75)

    total_items = 0
    encontrados = 0

    for cat in ENTREGABLES:
        print(f"\n[Categoria] {cat['categoria']}:")
        for ruta_rel, desc in cat["archivos"]:
            total_items += 1
            ruta = PROJECT_ROOT / ruta_rel
            if ruta.exists():
                encontrados += 1
                size_kb = ruta.stat().st_size / 1024
                print(f"  [OK]        {ruta_rel:<35} ({size_kb:>6.1f} KB) - {desc}")
            else:
                print(f"  [PENDIENTE] {ruta_rel:<35} - {desc}")

    porcentaje = (encontrados / total_items) * 100
    print("\n" + "=" * 75)
    print(f" ESTADO DE ENTREGABLES: {encontrados}/{total_items} completados ({porcentaje:.1f}%)")
    print("=" * 75)

    return encontrados, total_items

if __name__ == "__main__":
    verificar()
