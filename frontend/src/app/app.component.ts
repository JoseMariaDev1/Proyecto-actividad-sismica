import { Component, OnDestroy, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { LeafletDirective } from '@bluehalo/ngx-leaflet';
import * as L from 'leaflet';
import type { FeatureCollection, Point } from 'geojson';

export interface EarthquakeProperties {
  mag: number | null;
  magType?: string | null;
  place?: string | null;
  time: number;
  updated: number;
  country_id?: string | null;
  country_name?: string | null;
}

export interface EarthquakeFeature {
  type: 'Feature';
  id: string;
  geometry: {
    type: 'Point';
    coordinates: [number, number, number | null];
  };
  properties: EarthquakeProperties;
}

export interface ApiMetadata {
  generated?: number;
  last_ingestion?: number | null;
  mode?: string;
  count?: number;
  truncated?: boolean;
}

export interface EventsResponse {
  type: 'FeatureCollection';
  metadata?: ApiMetadata;
  features: EarthquakeFeature[];
}

export interface Config {
  mode: 'demo' | 'api';
  apiUrl: string;
  refreshMs: number;
  skipNgrokWarning: boolean;
}

export interface CountryOption {
  id: string;
  name: string;
}

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, LeafletDirective],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css'
})
export class AppComponent implements OnDestroy {
  // --- Estados reactivos principales ---
  readonly mode = signal<string>('Cargando configuración...');
  readonly status = signal<string>('Inicializando observatorio...');
  readonly lastRead = signal<string>('Sin lectura');
  readonly generated = signal<string>('Sin información');
  readonly lastIngestion = signal<string>('Esperando sincronización');
  readonly isFresh = signal<boolean>(true);
  readonly countriesStatus = signal<string>('Cargando catálogo');
  readonly omitted = signal<number>(0);
  readonly config = signal<Config | null>(null);

  // --- Modalidad de operación (Live vs Replay) ---
  readonly activeMode = signal<'live' | 'replay'>('live');

  // --- Filtros analíticos interactivos ---
  readonly filterMinMag = signal<number | null>(null);
  readonly filterCountry = signal<string>('');
  readonly filterDateStart = signal<string>('');
  readonly filterDateEnd = signal<string>('');

  // --- Tabla consultable accesible (Búsqueda, Ordenación y Paginación) ---
  readonly searchQuery = signal<string>('');
  readonly sortCol = signal<'time' | 'mag' | 'depth' | 'country' | 'place'>('time');
  readonly sortAsc = signal<boolean>(false);
  readonly currentPage = signal<number>(1);
  readonly pageSize = 10;

  // --- Datos en crudo y catálogo ---
  readonly rawFeatures = signal<EarthquakeFeature[]>([]);
  readonly countriesList = signal<CountryOption[]>([]);
  readonly backendStats = signal<any>(null);

  // --- Configuración y capas de Leaflet ---
  readonly options: L.MapOptions = {
    center: L.latLng(20, 0),
    zoom: 2,
    minZoom: 2,
    maxZoom: 9,
    preferCanvas: true,
    worldCopyJump: false
  };

  private map?: L.Map;
  private eventsLayer = L.layerGroup();
  private bordersLayer?: L.GeoJSON;
  private timer?: ReturnType<typeof setTimeout>;
  private controller = new AbortController();
  private destroyed = false;

  // =========================================================================
  // SEÑALES COMPUTADAS (Reactividad pura sin dependencias externas)
  // =========================================================================

  // 1. Filtrado en memoria de eventos
  readonly filteredEvents = computed(() => {
    let list = this.rawFeatures();
    const minM = this.filterMinMag();
    const cId = this.filterCountry();
    const sDate = this.filterDateStart() ? new Date(this.filterDateStart()).getTime() : null;
    const eDate = this.filterDateEnd() ? new Date(this.filterDateEnd()).getTime() : null;
    const q = this.searchQuery().trim().toLowerCase();

    return list.filter(item => {
      const p = item.properties;
      const coords = item.geometry.coordinates;

      // Filtro de magnitud mínima: si mag es null, no cumple filtro numérico
      if (minM !== null) {
        if (p.mag === null || p.mag < minM) return false;
      }

      // Filtro de país / región
      if (cId) {
        if (cId === 'sin_pais') {
          if (p.country_id !== null && p.country_name !== 'Sin país asignado') return false;
        } else if (p.country_id !== cId) {
          return false;
        }
      }

      // Filtro de rango temporal
      if (sDate !== null && p.time < sDate) return false;
      if (eDate !== null && p.time >= eDate) return false;

      // Filtro de búsqueda textual en tabla
      if (q) {
        const placeStr = (p.place ?? '').toLowerCase();
        const countryStr = (p.country_name ?? '').toLowerCase();
        const idStr = item.id.toLowerCase();
        if (!placeStr.includes(q) && !countryStr.includes(q) && !idStr.includes(q)) {
          return false;
        }
      }

      return true;
    });
  });

  // 2. Ordenación de eventos para la tabla
  readonly sortedEvents = computed(() => {
    const list = [...this.filteredEvents()];
    const col = this.sortCol();
    const asc = this.sortAsc();

    return list.sort((a, b) => {
      let valA: any;
      let valB: any;

      if (col === 'time') {
        valA = a.properties.time;
        valB = b.properties.time;
      } else if (col === 'mag') {
        valA = a.properties.mag ?? -999;
        valB = b.properties.mag ?? -999;
      } else if (col === 'depth') {
        valA = a.geometry.coordinates[2] ?? -999;
        valB = b.geometry.coordinates[2] ?? -999;
      } else if (col === 'country') {
        valA = (a.properties.country_name ?? 'Sin país').toLowerCase();
        valB = (b.properties.country_name ?? 'Sin país').toLowerCase();
      } else {
        valA = (a.properties.place ?? '').toLowerCase();
        valB = (b.properties.place ?? '').toLowerCase();
      }

      if (valA < valB) return asc ? -1 : 1;
      if (valA > valB) return asc ? 1 : -1;
      return 0;
    });
  });

  // 3. Paginación de la tabla
  readonly totalPages = computed(() => {
    return Math.max(1, Math.ceil(this.sortedEvents().length / this.pageSize));
  });

  readonly paginatedEvents = computed(() => {
    const p = Math.max(1, Math.min(this.currentPage(), this.totalPages()));
    const start = (p - 1) * this.pageSize;
    return this.sortedEvents().slice(start, start + this.pageSize);
  });

  // 4. Métricas analíticas KPI
  readonly kpiTotal = computed(() => this.filteredEvents().length);

  readonly kpiMaxMag = computed(() => {
    const mags = this.filteredEvents()
      .map(e => e.properties.mag)
      .filter((m): m is number => m !== null && Number.isFinite(m));
    return mags.length ? Math.max(...mags).toFixed(1) : 'ND';
  });

  readonly kpiMinMag = computed(() => {
    const mags = this.filteredEvents()
      .map(e => e.properties.mag)
      .filter((m): m is number => m !== null && Number.isFinite(m));
    return mags.length ? Math.min(...mags).toFixed(1) : 'ND';
  });

  readonly kpiNullMagCount = computed(() => {
    return this.filteredEvents().filter(e => e.properties.mag === null).length;
  });

  readonly kpiMaritimeCount = computed(() => {
    return this.filteredEvents().filter(e => !e.properties.country_id || e.properties.country_name === 'Sin país asignado').length;
  });

  readonly kpiAverageDepth = computed(() => {
    const depths = this.filteredEvents()
      .map(e => e.geometry.coordinates[2])
      .filter((d): d is number => d !== null && Number.isFinite(d));
    if (!depths.length) return 'ND';
    const sum = depths.reduce((acc, v) => acc + v, 0);
    return (sum / depths.length).toFixed(1) + ' km';
  });

  // 5. Comparación Histórica con 2025
  readonly histComparison = computed(() => {
    const stats = this.backendStats();
    if (stats?.comparacion_historica) {
      return stats.comparacion_historica;
    }
    // Cálculo de referencia local si no hay estadísticas del backend:
    // Año 2025: 18.302 sismos globales (M>=4.0) entre 365 días = 50.14 sismos/día
    const recentMag4 = this.filteredEvents().filter(e => (e.properties.mag ?? 0) >= 4.0).length;
    const mediaDiaria = 50.14;
    const ratio = (recentMag4 / mediaDiaria).toFixed(2);
    return {
      recuento_ultimas_24h_mag4: recentMag4,
      total_eventos_2025_mag4: 18302,
      dias_totales_2025: 365,
      media_diaria_2025: mediaDiaria,
      ratio_reciente_vs_historico: ratio,
      nota: 'Denominador histórico: 365 días (incluyendo días con cero sismos). El periodo reciente puede estar incompleto por retrasos de red sismológica.'
    };
  });

  // 6. Distribución de Magnitudes
  readonly magDistribution = computed(() => {
    const list = this.filteredEvents();
    const buckets = { '<3.0': 0, '3.0–3.9': 0, '4.0–4.9': 0, '5.0–5.9': 0, '>=6.0': 0, 'ND': 0 };
    for (const e of list) {
      const m = e.properties.mag;
      if (m === null || !Number.isFinite(m)) buckets['ND']++;
      else if (m < 3.0) buckets['<3.0']++;
      else if (m < 4.0) buckets['3.0–3.9']++;
      else if (m < 5.0) buckets['4.0–4.9']++;
      else if (m < 6.0) buckets['5.0–5.9']++;
      else buckets['>=6.0']++;
    }
    const maxVal = Math.max(1, ...Object.values(buckets));
    return Object.entries(buckets).map(([label, count]) => ({
      label,
      count,
      pct: Math.round((count / (list.length || 1)) * 100),
      barWidth: Math.round((count / maxVal) * 100)
    }));
  });

  // 7. Distribución por Estratos de Profundidad
  readonly depthDistribution = computed(() => {
    const list = this.filteredEvents();
    const buckets = {
      superficial: { label: '<70 km (Superficial)', count: 0, color: '#eab308' },
      intermedio: { label: '70–299 km (Intermedio)', count: 0, color: '#f97316' },
      profundo: { label: '>=300 km (Profundo)', count: 0, color: '#a855f7' },
      nd: { label: 'No disponible (ND)', count: 0, color: '#64748b' }
    };

    for (const e of list) {
      const d = e.geometry.coordinates[2];
      if (d === null || !Number.isFinite(d)) buckets.nd.count++;
      else if (d < 70) buckets.superficial.count++;
      else if (d < 300) buckets.intermedio.count++;
      else buckets.profundo.count++;
    }

    const maxVal = Math.max(1, ...Object.values(buckets).map(b => b.count));
    return Object.values(buckets).map(b => ({
      ...b,
      pct: Math.round((b.count / (list.length || 1)) * 100),
      barWidth: Math.round((b.count / maxVal) * 100)
    }));
  });

  // 8. Top Países Afectados
  readonly topCountries = computed(() => {
    const counts: Record<string, number> = {};
    for (const e of this.filteredEvents()) {
      const name = e.properties.country_name || 'Sin país asignado';
      counts[name] = (counts[name] || 0) + 1;
    }
    const sorted = Object.entries(counts)
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 6);
    const maxCount = Math.max(1, ...(sorted.map(s => s.count)));
    return sorted.map(s => ({
      ...s,
      barWidth: Math.round((s.count / maxCount) * 100)
    }));
  });

  // 9. Agregación temporal por ventanas de 1 hora UTC
  readonly hourlyDistribution = computed(() => {
    const counts: Record<string, number> = {};
    for (const e of this.filteredEvents()) {
      const d = new Date(e.properties.time);
      if (!Number.isNaN(d.getTime())) {
        const hourStr = `${String(d.getUTCHours()).padStart(2, '0')}:00`;
        counts[hourStr] = (counts[hourStr] || 0) + 1;
      }
    }
    const sortedHours = Object.keys(counts).sort();
    const maxC = Math.max(1, ...Object.values(counts));
    return sortedHours.map(hour => ({
      hour,
      count: counts[hour],
      barHeight: Math.round((counts[hour] / maxC) * 80)
    }));
  });

  // =========================================================================
  // CICLO DE VIDA Y CARGA DEL MAPA
  // =========================================================================

  async onMapReady(map: L.Map): Promise<void> {
    this.map = map;

    // Capas base de mapas:
    // CartoDB Voyager es libre, usa datos OpenStreetMap y no bloquea localhost por Tile Usage Policy como tile.openstreetmap.org
    const cartoVoyager = L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
      maxZoom: 19,
      subdomains: 'abcd',
      noWrap: true,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
    }).addTo(map);

    const cartoPositron = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
      maxZoom: 19,
      subdomains: 'abcd',
      noWrap: true,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
    });

    const osmBase = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      noWrap: true,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    });

    // Fronteras de países (Natural Earth)
    this.bordersLayer = L.geoJSON(undefined, {
      style: { color: '#334155', weight: 1, fill: false },
      onEachFeature: (feature: any, layer: any) => {
        const name = document.createElement('span');
        name.textContent = feature.properties?.NAME_ES ?? feature.properties?.ADMIN ?? 'Sin nombre';
        layer.bindTooltip(name);
      }
    }).addTo(map);

    this.eventsLayer.addTo(map);

    L.control.layers(
      {
        'CartoDB Voyager (Recomendado)': cartoVoyager,
        'CartoDB Positron (Claro)': cartoPositron,
        'OpenStreetMap (Estándar)': osmBase
      },
      {
        'Fronteras (Natural Earth)': this.bordersLayer,
        'Terremotos': this.eventsLayer
      }
    ).addTo(map);

    map.attributionControl.addAttribution('Fronteras: Natural Earth · Datos reales: USGS');

    // 1. Cargar catálogo geográfico de países
    try {
      const countriesGeo = await this.readJson<FeatureCollection>('datos/paises.geojson');
      this.bordersLayer.addData(countriesGeo);
      
      const list: CountryOption[] = [];
      for (const feat of countriesGeo.features as any[]) {
        const p = feat.properties;
        if (p?.ADM0_A3) {
          list.push({
            id: p.ADM0_A3,
            name: p.NAME_ES || p.ADMIN || p.ADM0_A3
          });
        }
      }
      list.sort((a, b) => a.name.localeCompare(b.name, 'es'));
      this.countriesList.set(list);
      this.countriesStatus.set(`${list.length} países cargados`);
    } catch (err) {
      this.countriesStatus.set('No se pudo cargar el catálogo de países');
    }

    if (this.destroyed) return;

    // 2. Cargar configuración de public/config.json
    try {
      const cfg = await this.readJson<Config>('config.json');
      if (!['demo', 'api'].includes(cfg.mode)) throw new Error('Modo inválido en config.json');
      this.config.set(cfg);
      this.mode.set(cfg.mode === 'demo' ? 'DEMOSTRACIÓN · datos ficticios' : 'API · backend en vivo');
      await this.refresh();
    } catch {
      this.status.set('Error: revisa public/config.json');
    }
  }

  private async readJson<T>(url: string, headers: Record<string, string> = {}): Promise<T> {
    const response = await fetch(url, {
      headers,
      cache: 'no-store',
      signal: AbortSignal.any([this.controller.signal, AbortSignal.timeout(15000)])
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json() as Promise<T>;
  }

  async refresh(): Promise<void> {
    const cfg = this.config();
    if (!cfg) return;

    try {
      let eventsUrl = 'datos/terremotos-demo.geojson';
      const headers: Record<string, string> = {};

      if (cfg.mode === 'api') {
        const base = cfg.apiUrl.replace(/\/$/, '');
        const modeParam = this.activeMode();
        eventsUrl = `${base}/api/eventos?mode=${modeParam}`;
        if (cfg.skipNgrokWarning) {
          headers['ngrok-skip-browser-warning'] = '1';
        }

        // Consultar estadísticas completas de la API en paralelo
        this.fetchApiStats(base, headers, modeParam);
      }

      const data = await this.readJson<EventsResponse>(eventsUrl, headers);
      if (this.destroyed) return;

      if (data.type !== 'FeatureCollection' || !Array.isArray(data.features)) {
        throw new Error('Se esperaba una FeatureCollection GeoJSON válida');
      }

      this.rawFeatures.set(data.features);

      // Comprobar frescura y última ingesta
      if (data.metadata?.last_ingestion) {
        const lastIngMs = data.metadata.last_ingestion;
        this.lastIngestion.set(this.formatDate(lastIngMs));
        const diffMinutes = (Date.now() - lastIngMs) / (1000 * 60);
        this.isFresh.set(diffMinutes <= 15);
      } else {
        this.lastIngestion.set('En línea (USGS)');
        this.isFresh.set(true);
      }

      this.lastRead.set(new Date().toISOString());
      this.generated.set(this.formatDate(data.metadata?.generated));
      this.status.set(cfg.mode === 'demo' ? 'Demostración estática' : 'API conectada · Datos actualizados');

      // Actualizar capa gráfica en el mapa de Leaflet
      this.renderMapMarkers();
    } catch (err: any) {
      if (!this.destroyed) {
        this.status.set('No se pudo conectar a la API. Conservando última lectura.');
        this.isFresh.set(false);
      }
    } finally {
      if (!this.destroyed && cfg.mode === 'api') {
        clearTimeout(this.timer);
        this.timer = setTimeout(() => void this.refresh(), Math.max(30000, Number(cfg.refreshMs) || 60000));
      }
    }
  }

  private async fetchApiStats(apiBase: string, headers: Record<string, string>, mode: string) {
    try {
      const statsUrl = `${apiBase}/api/estadisticas?mode=${mode}`;
      const stats = await this.readJson<any>(statsUrl, headers);
      this.backendStats.set(stats);
    } catch {
      // Si falla endpoint de estadísticas, los computed signals se encargan del fallback local
    }
  }

  renderMapMarkers(): void {
    if (!this.map) return;

    const nextLayer = L.layerGroup();
    let omittedCount = 0;

    for (const feature of this.filteredEvents()) {
      const p = feature.properties;
      const coords = feature.geometry?.coordinates ?? [];
      const [lon, lat, depth] = coords;

      if (
        !p ||
        !Number.isFinite(lon) ||
        !Number.isFinite(lat) ||
        Math.abs(lon) > 180 ||
        Math.abs(lat) > 90
      ) {
        omittedCount++;
        continue;
      }

      const magnitude = typeof p.mag === 'number' && Number.isFinite(p.mag) ? p.mag : null;
      const depthOk = typeof depth === 'number' && Number.isFinite(depth);

      // Color codificado por estrato de profundidad:
      // Superficial (<70km) -> Amarillo | Intermedio (70-299km) -> Naranja | Profundo (>=300km) -> Púrpura | ND -> Gris
      const color = !depthOk
        ? '#64748b'
        : depth < 70
        ? '#eab308'
        : depth < 300
        ? '#f97316'
        : '#a855f7';

      // Radio proporcional a la magnitud (mínimo 4px para magnitud nula)
      const radius = magnitude === null
        ? 4
        : Math.max(4, Math.min(22, 4 + (magnitude + 1) * 2.2));

      const popup = document.createElement('div');
      popup.className = 'earthquake-popup';
      popup.innerHTML = `
        <div style="font-family: system-ui, sans-serif; font-size: 13px; line-height: 1.4;">
          <strong style="font-size: 14px; color: #0f172a;">${p.place ?? 'Sin descripción'}</strong>
          <div style="margin-top: 6px; display: grid; grid-template-columns: auto 1fr; gap: 4px 10px;">
            <span style="color: #64748b;">Magnitud:</span>
            <strong>${magnitude !== null ? magnitude.toFixed(1) + (p.magType ? ' (' + p.magType + ')' : '') : '<span style="color:#e11d48">ND (Sin calcular)</span>'}</strong>
            <span style="color: #64748b;">Profundidad:</span>
            <span>${depthOk ? depth.toFixed(1) + ' km' : 'ND'}</span>
            <span style="color: #64748b;">Fecha UTC:</span>
            <span>${this.formatDate(p.time)}</span>
            <span style="color: #64748b;">País:</span>
            <span>${p.country_name ?? 'Sin país asignado'}</span>
            <span style="color: #64748b;">ID USGS:</span>
            <code style="background: #f1f5f9; padding: 1px 4px; border-radius: 3px;">${feature.id}</code>
          </div>
        </div>
      `;

      L.circleMarker([lat, lon], {
        radius,
        color,
        fillColor: color,
        fillOpacity: 0.75,
        weight: 1.5
      })
        .bindPopup(popup)
        .addTo(nextLayer);
    }

    this.eventsLayer.clearLayers();
    this.eventsLayer.addLayer(nextLayer);
    this.omitted.set(omittedCount);
  }

  // --- Handlers de interacción del usuario ---

  setMode(mode: 'live' | 'replay'): void {
    this.activeMode.set(mode);
    this.refresh();
  }

  onMinMagChange(event: Event): void {
    const val = (event.target as HTMLSelectElement).value;
    this.filterMinMag.set(val === '' ? null : parseFloat(val));
    this.currentPage.set(1);
    this.renderMapMarkers();
  }

  onCountryChange(event: Event): void {
    const val = (event.target as HTMLSelectElement).value;
    this.filterCountry.set(val);
    this.currentPage.set(1);
    this.renderMapMarkers();
  }

  onDateStartChange(event: Event): void {
    const val = (event.target as HTMLInputElement).value;
    this.filterDateStart.set(val);
    this.currentPage.set(1);
    this.renderMapMarkers();
  }

  onDateEndChange(event: Event): void {
    const val = (event.target as HTMLInputElement).value;
    this.filterDateEnd.set(val);
    this.currentPage.set(1);
    this.renderMapMarkers();
  }

  onSearch(event: Event): void {
    const val = (event.target as HTMLInputElement).value;
    this.searchQuery.set(val);
    this.currentPage.set(1);
  }

  resetFilters(): void {
    this.filterMinMag.set(null);
    this.filterCountry.set('');
    this.filterDateStart.set('');
    this.filterDateEnd.set('');
    this.searchQuery.set('');
    this.currentPage.set(1);
    this.renderMapMarkers();
  }

  setSort(col: 'time' | 'mag' | 'depth' | 'country' | 'place'): void {
    if (this.sortCol() === col) {
      this.sortAsc.set(!this.sortAsc());
    } else {
      this.sortCol.set(col);
      this.sortAsc.set(false);
    }
  }

  changePage(newPage: number): void {
    if (newPage >= 1 && newPage <= this.totalPages()) {
      this.currentPage.set(newPage);
    }
  }

  formatDate(value: unknown): string {
    if (typeof value !== 'number' || !Number.isFinite(value)) return 'ND';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return 'ND';
    return d.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    clearTimeout(this.timer);
    this.controller.abort();
  }
}
