  connect();
  pollHealth();
  setInterval(pollHealth, 1000);
  requestAnimationFrame(tickLocal);
  requestAnimationFrame(panelTick);
