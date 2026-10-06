/**
 * Video Separator - Node.js front server
 * - Serves index.html
 * - Proxies /api/* to the Flask backend
 * - Streams SSE without buffering
 */

const path = require("path");
const express = require("express");
const cors = require("cors");
const { createProxyMiddleware } = require("http-proxy-middleware");

const PORT = parseInt(process.env.NODE_PORT || "5000", 10);
const FLASK_TARGET = process.env.FLASK_TARGET || "http://127.0.0.1:8000";

const app = express();
app.use(cors());
app.disable("x-powered-by");

// Serve the static UI
app.get("/", (_req, res) => {
  res.sendFile(path.join(__dirname, "index.html"));
});

app.get("/index.html", (_req, res) => {
  res.sendFile(path.join(__dirname, "index.html"));
});

// Proxy /api/* to Flask, with special handling for SSE (no buffering)
app.use(
  "/api",
  createProxyMiddleware({
    target: FLASK_TARGET,
    changeOrigin: true,
    ws: false,
    selfHandleResponse: false,
    onProxyRes(proxyRes, req) {
      // Disable any buffering for SSE
      if (req.url.startsWith("/events")) {
        proxyRes.headers["cache-control"] = "no-cache";
        proxyRes.headers["x-accel-buffering"] = "no";
        delete proxyRes.headers["content-length"];
      }
    },
    proxyTimeout: 0,
    timeout: 0,
  })
);

// Health probe
app.get("/health", (_req, res) => {
  res.json({ status: "ok", proxy_target: FLASK_TARGET });
});

// 404 fallback
app.use((_req, res) => {
  res.status(404).send("Not found");
});

app.listen(PORT, "0.0.0.0", () => {
  console.log(`[node] Video Separator front server listening on 0.0.0.0:${PORT}`);
  console.log(`[node] Proxying /api -> ${FLASK_TARGET}`);
});