import { mountDashboard, siteLoader } from "./modules/dashboard.js";

mountDashboard(document.getElementById("dash"), {
  mode: "site",
  hash: true,
  load: siteLoader(`${import.meta.env.BASE_URL}modules.json`),
});
