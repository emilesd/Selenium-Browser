import express from "express";
import cors from "cors";
import routes from "./routes";
import { errorHandler } from "./middlewares/error.middleware";
import { apiLogger } from "./middlewares/logger.middleware";
import authRoutes from "./routes/auth";
import { authenticateJWT } from "./middlewares/auth.middleware";
import dotenv from "dotenv";
import { startBackupCron } from "./cron/backupCheck";

dotenv.config();
const NODE_ENV = (
  process.env.NODE_ENV ||
  process.env.ENV ||
  "development"
).toLowerCase();

const app = express();

app.use(express.json());
app.use(express.urlencoded({ extended: true })); // For form data
app.use(apiLogger);

// --- CORS handling (flexible for dev and strict for prod) ---
/**
 * FRONTEND_URLS env value: comma-separated allowed origins
 * Example: FRONTEND_URLS=http://localhost:3000,http://192.168.1.8:3000
 */
const rawFrontendUrls =
  process.env.FRONTEND_URLS || process.env.FRONTEND_URL || "";
const FRONTEND_URLS = rawFrontendUrls
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

// helper to see if origin is allowed
function isOriginAllowed(origin?: string | null) {
  if (!origin) return true; // allow non-browser clients (curl/postman)

  if (NODE_ENV !== "production") {
    // Dev mode: allow localhost origins automatically
    if (
      origin.startsWith("http://localhost") ||
      origin.startsWith("http://127.0.0.1") ||
      origin.startsWith("http://192.168.0.238")
    )
      return true;
    // allow explicit FRONTEND_URLS if provided
    if (FRONTEND_URLS.includes(origin)) return true;
    // optionally allow the server's LAN IP if FRONTEND_LAN_IP is provided
    const lanIp = process.env.FRONTEND_LAN_IP;
    if (lanIp && origin.startsWith(`http://${lanIp}`)) return true;
    // fallback: deny if not matched
    return false;
  }

  // production: strict whitelist — must match configured FRONTEND_URLS exactly
  return FRONTEND_URLS.includes(origin);
}

app.use(
  cors({
    origin: (origin, cb) => {
      if (isOriginAllowed(origin)) return cb(null, true);
      cb(new Error(`CORS: Origin ${origin} not allowed`));
    },
    methods: ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allowedHeaders: ["Content-Type", "Authorization"],
    credentials: true,
  })
);

app.use("/api/auth", authRoutes);
app.use("/api", authenticateJWT, routes);

app.use(errorHandler);

//startig cron job
startBackupCron();

export default app;
