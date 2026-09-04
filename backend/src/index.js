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
// CREAR sistema
app.post('/api/sistemas', verificarToken, async (req, res) => {
  try {
    const { nombre, ubicacion, capacidadInstalada, fechaInstalacion } = req.body;

    if (!nombre || !ubicacion || !capacidadInstalada || !fechaInstalacion) {
      return res.status(400).json({ error: 'Faltan campos requeridos' });
    }

    const sistema = await prisma.sistema.create({
      data: {
        nombre,
        ubicacion,
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

    const { nombre, ubicacion, capacidadInstalada, fechaInstalacion } = req.body;

    const sistema = await prisma.sistema.update({
      where: { id: parseInt(req.params.id) },
      data: {
        ...(nombre && { nombre }),
        ...(ubicacion && { ubicacion }),
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

      // Pequeña variación aleatoria (+/- 5%) para que no se vea artificial
      const variacion = 0.95 + Math.random() * 0.1;

      const watts =
        capacidadWatts * factorSolar * factorClima * factorDegradacion * variacion;

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