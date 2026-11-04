#!/usr/bin/env python3
"""
Script de generación del seed SQL para la tabla 'paises' a partir del
archivo GeoJSON de Natural Earth en frontend/public/datos/paises.geojson.

Genera el archivo 'sql/02_seed_paises.sql' con 177 países estructurados
para inserción idempotente (INSERT INTO ... ON CONFLICT DO UPDATE).
"""

import json
import os
import sys

def escapar_sql(valor: str) -> str:
    """Escapa comillas simples para literales SQL."""
    if valor is None:
        return "NULL"
    escapado = str(valor).replace("'", "''").strip()
    return f"'{escapado}'"

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    geojson_path = os.path.join(base_dir, "frontend", "public", "datos", "paises.geojson")
    output_sql_path = os.path.join(base_dir, "sql", "02_seed_paises.sql")

    if not os.path.exists(geojson_path):
        print(f"Error: No se encontró el archivo GeoJSON en {geojson_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Leyendo países desde: {geojson_path}")
    with open(geojson_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    print(f"Total de entidades encontradas: {len(features)}")

    paises_vistos = set()
    lineas_sql = [
        "-- ============================================================================",
        "-- PROYECTO: Observatorio de Actividad Sísmica",
        "-- FICHERO: 02_seed_paises.sql",
        "-- DESCRIPCIÓN: Carga inicial del catálogo de 177 países de Natural Earth",
        "-- IDEMPOTENCIA: ON CONFLICT (code) DO UPDATE",
        "-- ============================================================================\n",
        "INSERT INTO paises (code, name_es, admin, continent, subregion) VALUES"
    ]

    valores = []
    for feat in features:
        props = feat.get("properties", {})
        code = props.get("ADM0_A3")
        if not code or len(code) != 3:
            print(f"Advertencia: Código inválido ignorado: {code}")
            continue

        if code in paises_vistos:
            print(f"Advertencia: Código duplicado detectado: {code}")
            continue
        paises_vistos.add(code)

        name_es = props.get("NAME_ES") or props.get("NAME") or code
        admin = props.get("ADMIN") or props.get("NAME") or code
        continent = props.get("CONTINENT")
        subregion = props.get("SUBREGION")

        sql_val = f"  ({escapar_sql(code)}, {escapar_sql(name_es)}, {escapar_sql(admin)}, {escapar_sql(continent)}, {escapar_sql(subregion)})"
        valores.append(sql_val)

    lineas_sql.append(",\n".join(valores))
    lineas_sql.append("""ON CONFLICT (code) DO UPDATE SET
  name_es   = EXCLUDED.name_es,
  admin     = EXCLUDED.admin,
  continent = EXCLUDED.continent,
  subregion = EXCLUDED.subregion;
""")

    contenido_final = "\n".join(lineas_sql)
    with open(output_sql_path, "w", encoding="utf-8") as f:
        f.write(contenido_final)

    print(f"Archivo generado exitosamente: {output_sql_path}")
    print(f"Total países procesados y exportados: {len(paises_vistos)}")

if __name__ == "__main__":
    main()
