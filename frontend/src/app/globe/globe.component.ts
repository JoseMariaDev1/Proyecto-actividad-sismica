import {
  Component,
  ElementRef,
  ViewChild,
  OnInit,
  AfterViewInit,
  OnDestroy,
  input,
  output,
  signal,
  computed,
  effect
} from '@angular/core';
import { CommonModule } from '@angular/common';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import type { FeatureCollection } from 'geojson';
import type { EarthquakeFeature } from '../app.component';

@Component({
  selector: 'app-globe',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './globe.component.html',
  styleUrl: './globe.component.css'
})
export class GlobeComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('globeCanvas', { static: true })
  canvasRef!: ElementRef<HTMLCanvasElement>;

  @ViewChild('containerRef', { static: true })
  containerRef!: ElementRef<HTMLDivElement>;

  // --- Inputs usando Angular Signals ---
  events = input<EarthquakeFeature[]>([]);
  selectedEventId = input<string | null>(null);
  countriesGeoJson = input<FeatureCollection | null>(null);

  // --- Outputs ---
  eventSelected = output<EarthquakeFeature>();
  eventHovered = output<EarthquakeFeature | null>();

  // --- Estados de Control del Globo ---
  readonly autoRotate = signal<boolean>(true);
  readonly textureMode = signal<'day' | 'night'>('day');
  readonly showBorders = signal<boolean>(true);
  readonly showClouds = signal<boolean>(true);
  readonly hoveredEvent = signal<EarthquakeFeature | null>(null);
  readonly tooltipPos = signal<{ x: number; y: number }>({ x: 0, y: 0 });
  readonly tooltipVisible = signal<boolean>(false);
  readonly isLoaded = signal<boolean>(false);

  // --- Three.js Internals ---
  private scene!: THREE.Scene;
  private camera!: THREE.PerspectiveCamera;
  private renderer!: THREE.WebGLRenderer;
  private controls!: OrbitControls;

  private earthGroup = new THREE.Group();
  private earthMesh!: THREE.Mesh;
  private cloudsMesh!: THREE.Mesh;
  private atmosphereMesh!: THREE.Mesh;
  private starField!: THREE.Points;
  private bordersLine: THREE.LineSegments | null = null;
  private markersGroup = new THREE.Group();
  private ripplesGroup = new THREE.Group();

  private dayTexture!: THREE.Texture;
  private nightTexture!: THREE.Texture;
  private bumpTexture!: THREE.Texture;
  private cloudsTexture!: THREE.Texture;

  private raycaster = new THREE.Raycaster();
  private mouse = new THREE.Vector2(-999, -999);
  private resizeObserver?: ResizeObserver;
  private animFrameId?: number;
  private isDestroyed = false;

  // Animación de cámara orbital (Slerp)
  private targetCameraPos: THREE.Vector3 | null = null;
  private targetDistance = 220;

  // Pulso temporal para ondas sísmicas
  private rippleTime = 0;

  // Radio base del planeta Tierra en unidades de Three.js
  readonly GLOBE_RADIUS = 100;

  constructor() {
    // Re-render marcadores cuando cambian los eventos filtrados o la selección
    effect(() => {
      const currentEvents = this.events();
      const selectedId = this.selectedEventId();
      if (this.isLoaded()) {
        this.updateEarthquakeMarkers(currentEvents, selectedId);
      }
    });

    // Re-render fronteras cuando llega el GeoJSON
    effect(() => {
      const geo = this.countriesGeoJson();
      if (this.isLoaded() && geo) {
        this.buildCountryBorders(geo);
      }
    });
  }

  ngOnInit(): void {}

  ngAfterViewInit(): void {
    this.initThree();
    this.loadTexturesAndBuildScene();
    this.setupResizeObserver();
    this.animate();
  }

  // =========================================================================
  // INICIALIZACIÓN DE THREE.JS
  // =========================================================================

  private initThree(): void {
    const container = this.containerRef.nativeElement;
    const canvas = this.canvasRef.nativeElement;

    const width = container.clientWidth || 800;
    const height = container.clientHeight || 600;

    // 1. Escena
    this.scene = new THREE.Scene();
    this.scene.background = null;

    // 2. Cámara
    this.camera = new THREE.PerspectiveCamera(45, width / height, 0.5, 2000);
    this.camera.position.set(0, 40, 260);

    // 3. Renderizador WebGL
    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      powerPreference: 'high-performance'
    });
    this.renderer.setSize(width, height);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.15;

    // 4. OrbitControls con amortiguación
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.05;
    this.controls.rotateSpeed = 0.8;
    this.controls.zoomSpeed = 1.0;
    this.controls.minDistance = 120; // Previene atravesar la corteza terrestre
    this.controls.maxDistance = 480; // Mantiene el planeta en campo visual
    this.controls.enablePan = false; // Mantiene el centro gravitacional en (0,0,0)
    this.controls.autoRotate = this.autoRotate();
    this.controls.autoRotateSpeed = 0.6;

    // 5. Iluminación ambiental y solar
    const ambientLight = new THREE.AmbientLight(0xdde8ff, 0.6);
    this.scene.add(ambientLight);

    const sunLight = new THREE.DirectionalLight(0xffffff, 1.4);
    sunLight.position.set(250, 150, 200);
    this.scene.add(sunLight);

    const rimLight = new THREE.DirectionalLight(0x38bdf8, 0.45);
    rimLight.position.set(-200, -100, -200);
    this.scene.add(rimLight);

    // 6. Grupos
    this.scene.add(this.earthGroup);
    this.earthGroup.add(this.markersGroup);
    this.earthGroup.add(this.ripplesGroup);

    // 7. Campo estelar (estrellas cósmicas)
    this.createStarField();
  }

  // =========================================================================
  // CREACIÓN DEL PLANETA TIERRA Y TEXTURAS
  // =========================================================================

  private loadTexturesAndBuildScene(): void {
    const loader = new THREE.TextureLoader();

    this.dayTexture = loader.load('textures/earth-blue-marble.jpg');
    this.dayTexture.colorSpace = THREE.SRGBColorSpace;

    this.nightTexture = loader.load('textures/earth-night.jpg');
    this.nightTexture.colorSpace = THREE.SRGBColorSpace;

    this.bumpTexture = loader.load('textures/earth-topology.png');
    this.cloudsTexture = loader.load('textures/earth-clouds.png');

    // 1. Esfera de la Tierra
    const earthGeometry = new THREE.SphereGeometry(this.GLOBE_RADIUS, 64, 64);
    const earthMaterial = new THREE.MeshStandardMaterial({
      map: this.dayTexture,
      bumpMap: this.bumpTexture,
      bumpScale: 1.8,
      roughness: 0.65,
      metalness: 0.1
    });

    this.earthMesh = new THREE.Mesh(earthGeometry, earthMaterial);
    this.earthGroup.add(this.earthMesh);

    // 2. Capa de nubes dinámicas
    const cloudsGeometry = new THREE.SphereGeometry(this.GLOBE_RADIUS + 1.2, 64, 64);
    const cloudsMaterial = new THREE.MeshStandardMaterial({
      map: this.cloudsTexture,
      transparent: true,
      opacity: 0.38,
      blending: THREE.NormalBlending,
      depthWrite: false
    });
    this.cloudsMesh = new THREE.Mesh(cloudsGeometry, cloudsMaterial);
    this.earthGroup.add(this.cloudsMesh);

    // 3. Resplandor atmosférico (Halo azul orbital)
    this.createAtmosphere();

    this.isLoaded.set(true);

    const ev = this.events();
    if (ev && ev.length) {
      this.updateEarthquakeMarkers(ev, this.selectedEventId());
    }

    const geo = this.countriesGeoJson();
    if (geo) {
      this.buildCountryBorders(geo);
    }
  }

  private createAtmosphere(): void {
    const atmoGeometry = new THREE.SphereGeometry(this.GLOBE_RADIUS + 3.8, 64, 64);
    const atmoMaterial = new THREE.ShaderMaterial({
      vertexShader: `
        varying vec3 vNormal;
        void main() {
          vNormal = normalize(normalMatrix * normal);
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: `
        varying vec3 vNormal;
        void main() {
          float intensity = pow(0.68 - dot(vNormal, vec3(0.0, 0.0, 1.0)), 2.8);
          gl_FragColor = vec4(0.22, 0.74, 0.97, 1.0) * intensity * 0.75;
        }
      `,
      blending: THREE.AdditiveBlending,
      side: THREE.BackSide,
      transparent: true,
      depthWrite: false
    });

    this.atmosphereMesh = new THREE.Mesh(atmoGeometry, atmoMaterial);
    this.scene.add(this.atmosphereMesh);
  }

  private createStarField(): void {
    const starCount = 1800;
    const starGeometry = new THREE.BufferGeometry();
    const starPositions = new Float32Array(starCount * 3);
    const starColors = new Float32Array(starCount * 3);

    for (let i = 0; i < starCount; i++) {
      const r = 450 + Math.random() * 450;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);

      starPositions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      starPositions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      starPositions[i * 3 + 2] = r * Math.cos(phi);

      const brightness = 0.5 + Math.random() * 0.5;
      starColors[i * 3] = brightness * 0.9;
      starColors[i * 3 + 1] = brightness * 0.95;
      starColors[i * 3 + 2] = brightness;
    }

    starGeometry.setAttribute('position', new THREE.BufferAttribute(starPositions, 3));
    starGeometry.setAttribute('color', new THREE.BufferAttribute(starColors, 3));

    const starMaterial = new THREE.PointsMaterial({
      size: 1.5,
      vertexColors: true,
      transparent: true,
      opacity: 0.8,
      sizeAttenuation: false
    });

    this.starField = new THREE.Points(starGeometry, starMaterial);
    this.scene.add(this.starField);
  }

  // =========================================================================
  // FRONTERAS DE PAÍSES (Natural Earth GeoJSON)
  // =========================================================================

  private buildCountryBorders(geo: FeatureCollection): void {
    if (this.bordersLine) {
      this.earthGroup.remove(this.bordersLine);
      this.bordersLine.geometry.dispose();
      this.bordersLine = null;
    }

    const segments: number[] = [];
    const R = this.GLOBE_RADIUS + 0.25;

    for (const feat of geo.features as any[]) {
      const geom = feat.geometry;
      if (!geom) continue;

      if (geom.type === 'Polygon') {
        for (const ring of geom.coordinates) {
          this.addRingToSegments(ring, segments, R);
        }
      } else if (geom.type === 'MultiPolygon') {
        for (const poly of geom.coordinates) {
          for (const ring of poly) {
            this.addRingToSegments(ring, segments, R);
          }
        }
      }
    }

    if (!segments.length) return;

    const lineGeom = new THREE.BufferGeometry();
    lineGeom.setAttribute('position', new THREE.Float32BufferAttribute(segments, 3));

    const lineMat = new THREE.LineBasicMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.35,
      linewidth: 1
    });

    this.bordersLine = new THREE.LineSegments(lineGeom, lineMat);
    this.bordersLine.visible = this.showBorders();
    this.earthGroup.add(this.bordersLine);
  }

  private addRingToSegments(ring: [number, number][], segments: number[], R: number): void {
    for (let i = 0; i < ring.length - 1; i++) {
      // Ignorar saltos que cruzan el antimeridiano (-180 / +180) para evitar líneas que atraviesen el globo
      if (Math.abs(ring[i][0] - ring[i + 1][0]) > 180) continue;

      const p1 = this.latLonToVector3(ring[i][1], ring[i][0], R);
      const p2 = this.latLonToVector3(ring[i + 1][1], ring[i + 1][0], R);
      segments.push(p1.x, p1.y, p1.z, p2.x, p2.y, p2.z);
    }
  }

  // =========================================================================
  // REPRESENTACIÓN 3D DE TERREMOTOS (Columnas, orbes y ondas)
  // =========================================================================

  private updateEarthquakeMarkers(events: EarthquakeFeature[], selectedId: string | null): void {
    // 1. Limpiar marcadores y ondas liberando recursos WebGL
    while (this.markersGroup.children.length > 0) {
      const obj = this.markersGroup.children[0] as THREE.Mesh;
      this.markersGroup.remove(obj);
      if (obj.geometry) obj.geometry.dispose();
      if (Array.isArray(obj.material)) {
        obj.material.forEach(m => m.dispose());
      } else if (obj.material) {
        obj.material.dispose();
      }
    }

    while (this.ripplesGroup.children.length > 0) {
      const obj = this.ripplesGroup.children[0] as THREE.Mesh;
      this.ripplesGroup.remove(obj);
      if (obj.geometry) obj.geometry.dispose();
      if (obj.material) (obj.material as THREE.Material).dispose();
    }

    const R = this.GLOBE_RADIUS;

    for (const feature of events) {
      const coords = feature.geometry?.coordinates;
      if (!coords || coords.length < 2) continue;

      const [lon, lat, depth] = coords;
      if (
        !Number.isFinite(lon) ||
        !Number.isFinite(lat) ||
        Math.abs(lon) > 180 ||
        Math.abs(lat) > 90
      ) {
        continue;
      }

      const p = feature.properties;
      const mag = typeof p.mag === 'number' && Number.isFinite(p.mag) ? p.mag : null;
      const depthOk = typeof depth === 'number' && Number.isFinite(depth);
      const isSelected = feature.id === selectedId;

      // Color por estrato de profundidad:
      // Superficial (<70km) -> Amarillo Oro | Intermedio (70-299km) -> Naranja | Profundo (>=300km) -> Púrpura | ND -> Cian
      const hexColor = !depthOk
        ? 0x64748b
        : depth < 70
        ? 0xeab308
        : depth < 300
        ? 0xf97316
        : 0xa855f7;

      // Altura y radio del pilar sísmico proporcional a la magnitud
      const pillarHeight = mag === null
        ? 3.8
        : Math.max(3.2, Math.min(30.0, 3.2 + (mag - 1.5) * 3.8));

      const pillarRadius = mag === null
        ? 0.7
        : Math.max(0.7, Math.min(3.0, 0.6 + (mag * 0.3)));

      const surfacePos = this.latLonToVector3(lat, lon, R);
      const normal = surfacePos.clone().normalize();

      // Geometría del pilar cilíndrico perpendicular a la superficie
      const cylinderGeom = new THREE.CylinderGeometry(
        pillarRadius * 0.7,
        pillarRadius,
        pillarHeight,
        8
      );
      cylinderGeom.translate(0, pillarHeight / 2, 0);

      const cylinderMat = new THREE.MeshStandardMaterial({
        color: hexColor,
        emissive: hexColor,
        emissiveIntensity: isSelected ? 1.0 : 0.5,
        roughness: 0.3,
        metalness: 0.2,
        transparent: true,
        opacity: isSelected ? 1.0 : 0.88
      });

      const pillarMesh = new THREE.Mesh(cylinderGeom, cylinderMat);
      pillarMesh.position.copy(surfacePos);
      pillarMesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), normal);

      pillarMesh.userData = { earthquake: feature };
      this.markersGroup.add(pillarMesh);

      // Orbe brillante en la punta del pilar (más generoso para facilidad de clic)
      const tipRadius = isSelected
        ? Math.max(2.6, pillarRadius * 2.2)
        : Math.max(1.8, pillarRadius * 1.6);

      const tipGeom = new THREE.SphereGeometry(tipRadius, 14, 14);
      const tipMat = new THREE.MeshStandardMaterial({
        color: isSelected ? 0xffffff : hexColor,
        emissive: hexColor,
        emissiveIntensity: isSelected ? 1.6 : 0.85,
        roughness: 0.2
      });

      const tipMesh = new THREE.Mesh(tipGeom, tipMat);
      const tipPos = surfacePos.clone().add(normal.clone().multiplyScalar(pillarHeight));
      tipMesh.position.copy(tipPos);
      tipMesh.userData = { earthquake: feature };
      this.markersGroup.add(tipMesh);

      // Ondas sísmicas circulares (para sismos fuertes M>=4.5 o seleccionado)
      if (isSelected || (mag !== null && mag >= 4.5)) {
        this.createSeismicRipple(surfacePos, normal, hexColor, isSelected);
      }
    }
  }

  private createSeismicRipple(
    pos: THREE.Vector3,
    normal: THREE.Vector3,
    color: number,
    isSelected: boolean
  ): void {
    const ringGeom = new THREE.RingGeometry(0.8, 1.8, 24);
    const ringMat = new THREE.MeshBasicMaterial({
      color,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: isSelected ? 0.9 : 0.6,
      depthWrite: false
    });

    const ringMesh = new THREE.Mesh(ringGeom, ringMat);
    ringMesh.position.copy(pos.clone().add(normal.clone().multiplyScalar(0.3)));
    ringMesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal);

    ringMesh.userData = {
      baseScale: 1.0,
      maxScale: isSelected ? 6.5 : 4.0,
      phase: Math.random() * Math.PI * 2
    };

    this.ripplesGroup.add(ringMesh);
  }

  // =========================================================================
  // FÓRMULA MATEMÁTICA: LAT/LON A VECTOR CARTESIANO 3D
  // =========================================================================

  private latLonToVector3(lat: number, lon: number, radius: number): THREE.Vector3 {
    const phi = (lon + 180) * (Math.PI / 180);
    const theta = (90 - lat) * (Math.PI / 180);

    const x = -radius * Math.cos(phi) * Math.sin(theta);
    const y = radius * Math.cos(theta);
    const z = radius * Math.sin(phi) * Math.sin(theta);

    return new THREE.Vector3(x, y, z);
  }

  // =========================================================================
  // CONTROLES DE USUARIO E INTERACTIVIDAD
  // =========================================================================

  toggleAutoRotate(): void {
    const next = !this.autoRotate();
    this.autoRotate.set(next);
    if (this.controls) {
      this.controls.autoRotate = next;
    }
  }

  setTextureMode(mode: 'day' | 'night'): void {
    this.textureMode.set(mode);
    if (this.earthMesh && this.dayTexture && this.nightTexture) {
      const mat = this.earthMesh.material as THREE.MeshStandardMaterial;
      mat.map = mode === 'day' ? this.dayTexture : this.nightTexture;
      mat.needsUpdate = true;
    }
  }

  toggleBorders(): void {
    const next = !this.showBorders();
    this.showBorders.set(next);
    if (this.bordersLine) {
      this.bordersLine.visible = next;
    }
  }

  toggleClouds(): void {
    const next = !this.showClouds();
    this.showClouds.set(next);
    if (this.cloudsMesh) {
      this.cloudsMesh.visible = next;
    }
  }

  resetCamera(): void {
    this.targetCameraPos = new THREE.Vector3(0, 40, 260);
    this.targetDistance = 260;
    this.controls.target.set(0, 0, 0);
  }

  focusOnLocation(lat: number, lon: number, distance: number = 220): void {
    const surfacePos = this.latLonToVector3(lat, lon, this.GLOBE_RADIUS);
    const normal = surfacePos.clone().normalize();
    this.targetDistance = distance;
    this.targetCameraPos = normal.clone().multiplyScalar(distance);

    // Pausar auto-rotación momentáneamente durante el enfoque para evitar oscilaciones
    if (this.controls.autoRotate) {
      this.controls.autoRotate = false;
    }
  }

  // =========================================================================
  // GESTIÓN DE EVENTOS DE RATÓN (Raycasting)
  // =========================================================================

  onPointerMove(event: MouseEvent): void {
    const container = this.containerRef.nativeElement;
    const rect = container.getBoundingClientRect();

    const clientX = event.clientX - rect.left;
    const clientY = event.clientY - rect.top;

    this.mouse.x = (clientX / rect.width) * 2 - 1;
    this.mouse.y = -(clientY / rect.height) * 2 + 1;

    this.raycaster.setFromCamera(this.mouse, this.camera);
    const intersects = this.raycaster.intersectObjects(this.markersGroup.children, false);

    if (intersects.length > 0) {
      const hit = intersects[0].object;
      const eq = hit.userData?.['earthquake'] as EarthquakeFeature | undefined;

      if (eq) {
        container.style.cursor = 'pointer';
        this.hoveredEvent.set(eq);

        // Clamping en los bordes de la ventana para que el tooltip nunca quede recortado
        let posX = event.clientX + 14;
        let posY = event.clientY - 14;

        if (posX + 310 > window.innerWidth) {
          posX = event.clientX - 310;
        }
        if (posY + 220 > window.innerHeight) {
          posY = window.innerHeight - 230;
        }

        this.tooltipPos.set({ x: posX, y: posY });
        this.tooltipVisible.set(true);
        this.eventHovered.emit(eq);
        return;
      }
    }

    container.style.cursor = 'grab';
    if (this.hoveredEvent() !== null) {
      this.hoveredEvent.set(null);
      this.tooltipVisible.set(false);
      this.eventHovered.emit(null);
    }
  }

  onPointerDown(event: MouseEvent): void {
    this.containerRef.nativeElement.style.cursor = 'grabbing';
  }

  onPointerUp(event: MouseEvent): void {
    this.containerRef.nativeElement.style.cursor = 'grab';
  }

  onClick(event: MouseEvent): void {
    const container = this.containerRef.nativeElement;
    const rect = container.getBoundingClientRect();

    const clientX = event.clientX - rect.left;
    const clientY = event.clientY - rect.top;

    this.mouse.x = (clientX / rect.width) * 2 - 1;
    this.mouse.y = -(clientY / rect.height) * 2 + 1;

    this.raycaster.setFromCamera(this.mouse, this.camera);
    const intersects = this.raycaster.intersectObjects(this.markersGroup.children, false);

    if (intersects.length > 0) {
      const hit = intersects[0].object;
      const eq = hit.userData?.['earthquake'] as EarthquakeFeature | undefined;

      if (eq) {
        this.eventSelected.emit(eq);
        const [lon, lat] = eq.geometry.coordinates;
        this.focusOnLocation(lat, lon);
      }
    }
  }

  onPointerLeave(): void {
    this.tooltipVisible.set(false);
    this.hoveredEvent.set(null);
    this.eventHovered.emit(null);
  }

  // =========================================================================
  // LOOP DE RENDERIZADO Y ANIMACIÓN
  // =========================================================================

  private animate = (): void => {
    if (this.isDestroyed) return;

    this.animFrameId = requestAnimationFrame(this.animate);

    // 1. Rotación lenta de las nubes (más veloz que la corteza terrestre)
    if (this.cloudsMesh && this.showClouds()) {
      this.cloudsMesh.rotation.y += 0.00035;
    }

    // 2. Ondas sísmicas pulsantes
    this.rippleTime += 0.035;
    for (const ripple of this.ripplesGroup.children as THREE.Mesh[]) {
      const u = ripple.userData;
      if (u) {
        const cycle = (Math.sin(this.rippleTime * 2 + u.phase) + 1) / 2;
        const scale = u.baseScale + cycle * (u.maxScale - u.baseScale);
        ripple.scale.set(scale, scale, 1);
        const mat = ripple.material as THREE.MeshBasicMaterial;
        mat.opacity = (1 - cycle) * 0.8;
      }
    }

    // 3. Interpolación orbital suave (Slerp en esfera) sin atravesar el planeta
    if (this.targetCameraPos) {
      const currentDir = this.camera.position.clone().normalize();
      const targetDir = this.targetCameraPos.clone().normalize();

      // Si los vectores son casi opuestos, agregamos una leve perturbación para evitar singularidad
      if (currentDir.distanceTo(targetDir) > 1.96) {
        currentDir.x += 0.02;
        currentDir.normalize();
      }

      currentDir.lerp(targetDir, 0.07).normalize();
      const currentDist = this.camera.position.length();
      const newDist = THREE.MathUtils.lerp(currentDist, this.targetDistance, 0.07);

      this.camera.position.copy(currentDir.multiplyScalar(newDist));
      this.controls.update();

      if (this.camera.position.distanceTo(this.targetCameraPos) < 2.0) {
        this.targetCameraPos = null;
        if (this.autoRotate()) {
          this.controls.autoRotate = true;
        }
      }
    } else {
      this.controls.update();
    }

    // 4. Render
    this.renderer.render(this.scene, this.camera);
  };

  private setupResizeObserver(): void {
    const container = this.containerRef.nativeElement;
    this.resizeObserver = new ResizeObserver(() => {
      if (this.isDestroyed || !this.renderer || !this.camera) return;
      const width = container.clientWidth || 800;
      const height = container.clientHeight || 600;
      this.camera.aspect = width / height;
      this.camera.updateProjectionMatrix();
      this.renderer.setSize(width, height);
    });
    this.resizeObserver.observe(container);
  }

  ngOnDestroy(): void {
    this.isDestroyed = true;
    if (this.animFrameId) cancelAnimationFrame(this.animFrameId);
    if (this.resizeObserver) this.resizeObserver.disconnect();

    if (this.controls) this.controls.dispose();
    if (this.renderer) this.renderer.dispose();
  }
}
