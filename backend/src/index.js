require('dotenv').config();

const express = require('express');
const cors = require('cors');
const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
const { PrismaClient } = require('@prisma/client');
const { PrismaPg } = require('@prisma/adapter-pg');
const verificarToken = require('./middleware/auth');
require('dotenv').config();

const app = express();
const adapter = new PrismaPg({ connectionString: process.env.DATABASE_URL });
const prisma = new PrismaClient({ adapter });

app.use(cors());
app.use(express.json());

app.get('/api/health', (req, res) => {
  res.json({ status: 'SolarCare backend funcionando' });
});

// REGISTRO
app.post('/api/auth/register', async (req, res) => {
  try {
    const { nombre, email, password } = req.body;

    if (!nombre || !email || !password) {
      return res.status(400).json({ error: 'Faltan campos requeridos' });
    }

    const existente = await prisma.usuario.findUnique({ where: { email } });
    if (existente) {
      return res.status(400).json({ error: 'Ese email ya está registrado' });
    }

    const passwordHash = await bcrypt.hash(password, 10);

    const usuario = await prisma.usuario.create({
      data: { nombre, email, password: passwordHash },
    });

    res.status(201).json({
      id: usuario.id,
      nombre: usuario.nombre,
      email: usuario.email,
    });
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Error al registrar usuario' });
  }
});

// LOGIN
app.post('/api/auth/login', async (req, res) => {
  try {
    const { email, password } = req.body;

    const usuario = await prisma.usuario.findUnique({ where: { email } });
    if (!usuario) {
      return res.status(401).json({ error: 'Credenciales inválidas' });
    }

    const passwordValida = await bcrypt.compare(password, usuario.password);
    if (!passwordValida) {
      return res.status(401).json({ error: 'Credenciales inválidas' });
    }

    const token = jwt.sign(
      { id: usuario.id, email: usuario.email },
      process.env.JWT_SECRET,
      { expiresIn: '7d' }
    );

    res.json({
      token,
      usuario: { id: usuario.id, nombre: usuario.nombre, email: usuario.email },
    });
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Error al iniciar sesión' });
  }
});

async function geocodificarUbicacion(nombre) {
  try {
    const resp = await fetch(
      `https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(nombre)}&count=1&language=es&format=json`
    );
    const datos = await resp.json();
    if (datos.results && datos.results.length > 0) {
      const r = datos.results[0];
      return {
        latitude: r.latitude,
        longitude: r.longitude,
        nombreResuelto: `${r.name}${r.admin1 ? ', ' + r.admin1 : ''}`,
      };
    }
    return null;
  } catch (err) {
    return null;
  }
}

app.get('/api/ciudades-honduras', verificarToken, async (req, res) => {
  try {
    const ciudades = await prisma.ciudadHonduras.findMany({
      orderBy: { nombre: 'asc' },
    });
    res.json(ciudades);
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Error al obtener las ciudades' });
  }
});

app.get('/api/clima-actual', verificarToken, async (req, res) => {
  try {
    const ubicacionSolicitada = req.query.ubicacion;
    let lat = 15.5, lon = -88.03, nombreResuelto = 'San Pedro Sula';
    let ubicacionEncontrada = true;
    const latitudSolicitada = Number(req.query.latitud);
    const longitudSolicitada = Number(req.query.longitud);

    if (Number.isFinite(latitudSolicitada) && Number.isFinite(longitudSolicitada)) {
      lat = latitudSolicitada;
      lon = longitudSolicitada;
      nombreResuelto = ubicacionSolicitada || nombreResuelto;
    } else if (ubicacionSolicitada) {
      const ciudad = await prisma.ciudadHonduras.findFirst({
        where: { nombre: ubicacionSolicitada },
      });
      if (ciudad) {
        lat = ciudad.latitud;
        lon = ciudad.longitud;
        nombreResuelto = ciudad.nombre;
      } else {
        const geo = await geocodificarUbicacion(ubicacionSolicitada);
        if (geo) {
          lat = geo.latitude;
          lon = geo.longitude;
          nombreResuelto = geo.nombreResuelto;
        } else {
          ubicacionEncontrada = false;
        }
      }
    }

    const respuesta = await fetch(
      `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}&current=cloud_cover,precipitation,weather_code,temperature_2m`
    );
    const datos = await respuesta.json();
    const { cloud_cover, precipitation, weather_code, temperature_2m } = datos.current;

    let categoria;
    if (precipitation > 0 || (weather_code >= 51 && weather_code <= 99)) categoria = 'rain';
    else if (cloud_cover > 70) categoria = 'cloudy';
    else if (cloud_cover > 30) categoria = 'partial_clouds';
    else categoria = 'clear';

    res.json({
      categoria,
      temperatura: temperature_2m,
      cloudCover: cloud_cover,
      precipitation,
      weatherCode: weather_code,
      ubicacion: nombreResuelto,
      ubicacionEncontrada,
    });
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'No se pudo obtener el clima actual' });
  }
});

// CREAR sistema
app.post('/api/sistemas', verificarToken, async (req, res) => {
  try {
    const { nombre, ubicacion, latitud, longitud, capacidadInstalada, fechaInstalacion } = req.body;

    if (!nombre || !ubicacion || !capacidadInstalada || !fechaInstalacion) {
      return res.status(400).json({ error: 'Faltan campos requeridos' });
    }

    const sistema = await prisma.sistema.create({
      data: {
        nombre,
        ubicacion,
        ...(latitud != null && { latitud: parseFloat(latitud) }),
        ...(longitud != null && { longitud: parseFloat(longitud) }),
        capacidadInstalada: parseFloat(capacidadInstalada),
        fechaInstalacion: new Date(fechaInstalacion),
        usuarioId: req.usuario.id,
      },
    });

    res.status(201).json(sistema);
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Error al crear el sistema' });
  }
});

// LISTAR sistemas del usuario autenticado
app.get('/api/sistemas', verificarToken, async (req, res) => {
  try {
    const sistemas = await prisma.sistema.findMany({
      where: { usuarioId: req.usuario.id },
      orderBy: { createdAt: 'desc' },
    });
    res.json(sistemas);
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Error al obtener los sistemas' });
  }
});

// OBTENER un sistema específico (con sus lecturas)
app.get('/api/sistemas/:id', verificarToken, async (req, res) => {
  try {
    const sistema = await prisma.sistema.findUnique({
      where: { id: parseInt(req.params.id) },
      include: { lecturas: { orderBy: { timestamp: 'desc' }, take: 50 } },
    });

    if (!sistema || sistema.usuarioId !== req.usuario.id) {
      return res.status(404).json({ error: 'Sistema no encontrado' });
    }

    res.json(sistema);
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Error al obtener el sistema' });
  }
});

// ACTUALIZAR sistema
app.put('/api/sistemas/:id', verificarToken, async (req, res) => {
  try {
    const sistemaExistente = await prisma.sistema.findUnique({
      where: { id: parseInt(req.params.id) },
    });

    if (!sistemaExistente || sistemaExistente.usuarioId !== req.usuario.id) {
      return res.status(404).json({ error: 'Sistema no encontrado' });
    }

    const { nombre, ubicacion, latitud, longitud, capacidadInstalada, fechaInstalacion } = req.body;

    const sistema = await prisma.sistema.update({
      where: { id: parseInt(req.params.id) },
      data: {
        ...(nombre && { nombre }),
        ...(ubicacion && { ubicacion }),
        ...(latitud != null && { latitud: parseFloat(latitud) }),
        ...(longitud != null && { longitud: parseFloat(longitud) }),
        ...(capacidadInstalada && { capacidadInstalada: parseFloat(capacidadInstalada) }),
        ...(fechaInstalacion && { fechaInstalacion: new Date(fechaInstalacion) }),
      },
    });

    res.json(sistema);
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Error al actualizar el sistema' });
  }
});

// ELIMINAR sistema
app.delete('/api/sistemas/:id', verificarToken, async (req, res) => {
  try {
    const sistemaExistente = await prisma.sistema.findUnique({
      where: { id: parseInt(req.params.id) },
    });

    if (!sistemaExistente || sistemaExistente.usuarioId !== req.usuario.id) {
      return res.status(404).json({ error: 'Sistema no encontrado' });
    }

    await prisma.sistema.delete({ where: { id: parseInt(req.params.id) } });
    res.status(204).send();
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Error al eliminar el sistema' });
  }
});

// Lista fija de códigos válidos (simula los códigos de serie de baterías físicas reales)
const CODIGOS_BATERIA_VALIDOS = [
  'SC-BAT-1001', 'SC-BAT-1002', 'SC-BAT-1003', 'SC-BAT-1004', 'SC-BAT-1005',
  'SC-BAT-1006', 'SC-BAT-1007', 'SC-BAT-1008', 'SC-BAT-1009', 'SC-BAT-1010',
];

// AGREGAR batería (requiere código de activación válido y no usado antes)
app.post('/api/sistemas/:id/baterias', verificarToken, async (req, res) => {
  try {
    const sistema = await prisma.sistema.findUnique({
      where: { id: parseInt(req.params.id) },
    });

    if (!sistema || sistema.usuarioId !== req.usuario.id) {
      return res.status(404).json({ error: 'Sistema no encontrado' });
    }

    const { codigoActivacion, capacidadKwh, fechaInstalacion } = req.body;

    if (!codigoActivacion || !capacidadKwh || !fechaInstalacion) {
      return res.status(400).json({ error: 'Faltan campos requeridos' });
    }

    if (!CODIGOS_BATERIA_VALIDOS.includes(codigoActivacion)) {
      return res.status(400).json({ error: 'Código de activación inválido' });
    }

    const yaUsado = await prisma.bateria.findUnique({ where: { codigoActivacion } });
    if (yaUsado) {
      return res.status(400).json({ error: 'Este código ya fue utilizado' });
    }

    const bateria = await prisma.bateria.create({
      data: {
        capacidadKwh: parseFloat(capacidadKwh),
        fechaInstalacion: new Date(fechaInstalacion),
        codigoActivacion,
        sistemaId: sistema.id,
      },
    });

    res.status(201).json(bateria);
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Error al agregar la batería' });
  }
});

// LISTAR baterías de un sistema, con degradación individual y capacidad total
app.get('/api/sistemas/:id/baterias', verificarToken, async (req, res) => {
  try {
    const sistema = await prisma.sistema.findUnique({
      where: { id: parseInt(req.params.id) },
      include: { bateria: true },
    });

    if (!sistema || sistema.usuarioId !== req.usuario.id) {
      return res.status(404).json({ error: 'Sistema no encontrado' });
    }

    const TASA_DEGRADACION_ANUAL = 0.025;
    const bateriasRegistradas = Array.isArray(sistema.bateria)
      ? sistema.bateria
      : sistema.bateria
        ? [sistema.bateria]
        : [];
    const baterias = bateriasRegistradas.map((b) => {
      const años =
        (Date.now() - new Date(b.fechaInstalacion).getTime()) /
        (1000 * 60 * 60 * 24 * 365.25);
      const factorDegradacion = Math.max(0, 1 - TASA_DEGRADACION_ANUAL * años);
      return {
        ...b,
        factorDegradacion: Math.round(factorDegradacion * 1000) / 1000,
        capacidadActualKwh: Math.round(b.capacidadKwh * factorDegradacion * 100) / 100,
      };
    });

    const capacidadTotalActual = Math.round(
      baterias.reduce((suma, b) => suma + b.capacidadActualKwh, 0) * 100
    ) / 100;

    res.json({ baterias, capacidadTotalActual });
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Error al obtener las baterías' });
  }
});

// ELIMINAR una batería específica
app.delete('/api/sistemas/:id/baterias/:bateriaId', verificarToken, async (req, res) => {
  try {
    const sistema = await prisma.sistema.findUnique({
      where: { id: parseInt(req.params.id) },
    });

    if (!sistema || sistema.usuarioId !== req.usuario.id) {
      return res.status(404).json({ error: 'Sistema no encontrado' });
    }

    await prisma.bateria.delete({ where: { id: parseInt(req.params.bateriaId) } });
    res.status(204).send();
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Error al eliminar la batería' });
  }
});

// SIMULAR DA - genera lecturas realistas de watts para un sistema
app.post('/api/sistemas/:id/simular-dia', verificarToken, async (req, res) => {
  try {
    const sistema = await prisma.sistema.findUnique({
      where: { id: parseInt(req.params.id) },
    });

    if (!sistema || sistema.usuarioId !== req.usuario.id) {
      return res.status(404).json({ error: 'Sistema no encontrado' });
    }

    const { clima } = req.body; // 'clear', 'partial clouds', 'cloudy', 'rain'

    const factoresClima = {
      clear: 1.0,
      partial_clouds: 0.7,
      cloudy: 0.4,
      rain: 0.15,
    };

    const factorClima = factoresClima[clima];
    if (factorClima === undefined) {
      return res.status(400).json({
        error: "Clima inválido. Usa: 'clear', 'partial_clouds', 'cloudy' o 'rain'",
      });
    }

    // Degradación del panel: ~0.6% por año desde la instalación
    const TASA_DEGRADACION_ANUAL = 0.006;
    const añosDesdeInstalacion =
      (Date.now() - new Date(sistema.fechaInstalacion).getTime()) /
      (1000 * 60 * 60 * 24 * 365.25);
    const factorDegradacion = Math.max(
      0,
      1 - TASA_DEGRADACION_ANUAL * añosDesdeInstalacion
    );

    const capacidadWatts = sistema.capacidadInstalada * 1000; // kW -> W
    const horasDelDia = [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18];

    const hoy = new Date();
    hoy.setHours(0, 0, 0, 0);

    // Borra TODAS las lecturas simuladas anteriores de este sistema antes de insertar las nuevas
    await prisma.lectura.deleteMany({
      where: {
        sistemaId: sistema.id,
        origin: 'simulado',
      },
    });

    const lecturas = horasDelDia.map((hora) => {
      // Curva solar: 0 en los extremos (6am/6pm), máxima al mediodía
      const anguloSolar = Math.PI * ((hora - 6) / 12);
      const factorSolar = Math.max(0, Math.sin(anguloSolar));

      const watts =
        capacidadWatts * factorSolar * factorClima * factorDegradacion;

      const timestamp = new Date(hoy);
      timestamp.setHours(hora, 0, 0, 0);

      return {
        sistemaId: sistema.id,
        timestamp,
        watts: Math.round(watts * 100) / 100,
        origin: 'simulado',
      };
    });

    await prisma.lectura.createMany({ data: lecturas });

    res.status(201).json({
      mensaje: `Día simulado con clima '${clima}' para el sistema "${sistema.nombre}"`,
      factorDegradacion: Math.round(factorDegradacion * 1000) / 1000,
      lecturas,
    });
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Error al simular el día' });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Servidor corriendo en puerto ${PORT}`);
});