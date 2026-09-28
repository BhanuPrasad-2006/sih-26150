/**
 * SIH26150 — Interactive Forensic Acquisition & Carving Canvas Visualizer
 * Simulates: Disk Sector Scan -> Signature Carve -> Frame Reconstruct -> SHA-256 Seal
 */

(function () {
  const canvas = document.getElementById('forensicCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  let width = 0;
  let height = 0;
  let animationFrameId = null;
  let time = 0;
  let mouse = { x: 0, y: 0, targetX: 0, targetY: 0 };
  let isHovered = false;

  const hudSectors = document.getElementById('hudSectors');
  const hudFrames = document.getElementById('hudFrames');
  const hudHash = document.getElementById('hudHash');

  let sectorCount = 184320;
  let frameCount = 384;
  const sampleHashes = [
    '6ed2148c... VERIFIED',
    '3f8a91b2... VALID',
    '8c40fa91... SEALED',
    'e719b0ac... VERIFIED',
    'b44f2801... MATCH'
  ];

  function resize() {
    const rect = canvas.getBoundingClientRect();
    width = rect.width;
    height = rect.height;
    canvas.width = width * window.devicePixelRatio;
    canvas.height = height * window.devicePixelRatio;
    ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
  }

  window.addEventListener('resize', resize);
  resize();

  canvas.addEventListener('mousemove', function (e) {
    const rect = canvas.getBoundingClientRect();
    mouse.targetX = (e.clientX - rect.left) - width / 2;
    mouse.targetY = (e.clientY - rect.top) - height / 2;
    isHovered = true;
  });

  canvas.addEventListener('mouseleave', function () {
    mouse.targetX = 0;
    mouse.targetY = 0;
    isHovered = false;
  });

  // Data packets flying from disk to reconstruction
  const packets = [];
  const packetTypes = ['DHAV', 'HIK', 'NAL:0x67', 'NAL:0x65', 'PES', 'WFS', 'FRAME'];

  for (let i = 0; i < 18; i++) {
    packets.push({
      progress: Math.random(),
      speed: 0.005 + Math.random() * 0.008,
      type: packetTypes[Math.floor(Math.random() * packetTypes.length)],
      offsetY: (Math.random() - 0.5) * 44,
      size: 4 + Math.random() * 4
    });
  }

  function drawDisk(cx, cy, radius) {
    ctx.save();
    ctx.translate(cx, cy);

    // Subtle tilt based on mouse
    const tiltX = (mouse.x / width) * 0.18;
    const tiltY = (mouse.y / height) * 0.18;
    ctx.scale(1 + tiltX, 0.72 + tiltY);

    // Outer platter
    const grad = ctx.createRadialGradient(0, 0, radius * 0.15, 0, 0, radius);
    grad.addColorStop(0, '#091524');
    grad.addColorStop(0.65, '#07101b');
    grad.addColorStop(0.95, '#04070c');
    grad.addColorStop(1, 'rgba(0, 229, 255, 0.25)');

    ctx.beginPath();
    ctx.arc(0, 0, radius, 0, Math.PI * 2);
    ctx.fillStyle = grad;
    ctx.fill();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = 'rgba(0, 229, 255, 0.35)';
    ctx.stroke();

    // Concentric tracks
    const tracks = 5;
    for (let i = 1; i <= tracks; i++) {
      const r = (radius / (tracks + 1)) * i;
      ctx.beginPath();
      ctx.arc(0, 0, r, 0, Math.PI * 2);
      ctx.strokeStyle = i % 2 === 0 ? 'rgba(56, 189, 248, 0.18)' : 'rgba(16, 185, 129, 0.18)';
      ctx.setLineDash([4, 6]);
      ctx.stroke();
    }
    ctx.setLineDash([]);

    // Rotating sector blocks
    const numSectors = 24;
    const rot = time * 0.5;
    for (let s = 0; s < numSectors; s++) {
      const angle = (s / numSectors) * Math.PI * 2 + rot;
      const r = radius * 0.68;
      const sx = Math.cos(angle) * r;
      const sy = Math.sin(angle) * r;

      ctx.beginPath();
      ctx.arc(sx, sy, 3.2, 0, Math.PI * 2);
      if (s % 5 === 0) {
        ctx.fillStyle = '#10b981'; // carved video sector
      } else if (s % 3 === 0) {
        ctx.fillStyle = '#00e5ff'; // index cluster
      } else {
        ctx.fillStyle = 'rgba(100, 116, 139, 0.4)'; // raw unallocated
      }
      ctx.fill();
    }

    // Spindle hub
    ctx.beginPath();
    ctx.arc(0, 0, radius * 0.24, 0, Math.PI * 2);
    ctx.fillStyle = '#0b1626';
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#00e5ff';
    ctx.stroke();

    // Scan head / actuator arm
    const armAngle = Math.sin(time * 0.8) * 0.32 - 0.22;
    const armLen = radius * 1.05;
    const hx = Math.cos(armAngle) * armLen;
    const hy = Math.sin(armAngle) * armLen;

    ctx.beginPath();
    ctx.moveTo(radius * 1.15, -radius * 0.75);
    ctx.lineTo(hx, hy);
    ctx.lineWidth = 3;
    ctx.strokeStyle = '#38bdf8';
    ctx.stroke();

    // Laser read beam
    ctx.beginPath();
    ctx.arc(hx, hy, 4, 0, Math.PI * 2);
    ctx.fillStyle = '#00e5ff';
    ctx.shadowColor = '#00e5ff';
    ctx.shadowBlur = 12;
    ctx.fill();
    ctx.shadowBlur = 0;

    ctx.restore();
  }

  function drawReconstructionCore(cx, cy) {
    ctx.save();
    ctx.translate(cx, cy);

    // Frame chamber container
    ctx.fillStyle = 'rgba(11, 20, 34, 0.9)';
    ctx.strokeStyle = 'rgba(16, 185, 129, 0.4)';
    ctx.lineWidth = 1.5;
    const bw = 150;
    const bh = 100;
    ctx.fillRect(-bw / 2, -bh / 2, bw, bh);
    ctx.strokeRect(-bw / 2, -bh / 2, bw, bh);

    // Header label
    ctx.fillStyle = '#10b981';
    ctx.font = '9px "JetBrains Mono", monospace';
    ctx.fillText('RECONSTRUCT: CH-01', -bw / 2 + 10, -bh / 2 + 16);

    // Simulated CCTV viewport inside preview
    ctx.strokeStyle = 'rgba(56, 189, 248, 0.4)';
    ctx.lineWidth = 1;
    ctx.strokeRect(-bw / 2 + 10, -bh / 2 + 24, bw - 20, bh - 36);

    // Camera perspective grid
    ctx.beginPath();
    ctx.moveTo(-bw / 2 + 10, -bh / 2 + 24);
    ctx.lineTo(0, -6);
    ctx.lineTo(bw / 2 - 10, -bh / 2 + 24);
    ctx.strokeStyle = 'rgba(0, 229, 255, 0.25)';
    ctx.stroke();

    // Timestamp simulation
    const sec = Math.floor(time * 2) % 60;
    const timeStr = '2026-09-28 14:22:' + (sec < 10 ? '0' : '') + sec;
    ctx.fillStyle = '#94a3b8';
    ctx.font = '8px "JetBrains Mono", monospace';
    ctx.fillText(timeStr, -bw / 2 + 14, bh / 2 - 16);

    // Frame scan indicator
    const scanLineY = (-bh / 2 + 24) + ((time * 35) % (bh - 36));
    ctx.beginPath();
    ctx.moveTo(-bw / 2 + 10, scanLineY);
    ctx.lineTo(bw / 2 - 10, scanLineY);
    ctx.strokeStyle = 'rgba(16, 185, 129, 0.7)';
    ctx.stroke();

    ctx.restore();
  }

  function drawPackets(x1, y1, x2, y2) {
    packets.forEach(function (p) {
      p.progress += p.speed;
      if (p.progress > 1) p.progress = 0;

      const px = x1 + (x2 - x1) * p.progress;
      const py = y1 + (y2 - y1) * p.progress + p.offsetY * Math.sin(p.progress * Math.PI);

      ctx.save();
      ctx.fillStyle = p.progress > 0.65 ? '#10b981' : '#00e5ff';
      ctx.font = '8px "JetBrains Mono", monospace';
      ctx.fillText(p.type, px, py - 4);

      ctx.beginPath();
      ctx.arc(px, py, 2.5, 0, Math.PI * 2);
      ctx.fillStyle = p.progress > 0.65 ? '#10b981' : '#38bdf8';
      ctx.shadowColor = '#00e5ff';
      ctx.shadowBlur = 6;
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.restore();
    });
  }

  function animate() {
    time += 0.03;
    mouse.x += (mouse.targetX - mouse.x) * 0.08;
    mouse.y += (mouse.targetY - mouse.y) * 0.08;

    ctx.clearRect(0, 0, width, height);

    // Center locations
    const diskX = width * 0.28;
    const diskY = height * 0.52;
    const diskRadius = Math.min(width * 0.22, height * 0.42);

    const coreX = width * 0.76;
    const coreY = height * 0.52;

    // Stream pathway
    ctx.beginPath();
    ctx.moveTo(diskX, diskY);
    ctx.bezierCurveTo(diskX + 80, diskY - 60, coreX - 80, coreY - 60, coreX, coreY);
    ctx.strokeStyle = 'rgba(56, 189, 248, 0.18)';
    ctx.lineWidth = 2;
    ctx.stroke();

    drawDisk(diskX, diskY, diskRadius);
    drawPackets(diskX, diskY, coreX, coreY);
    drawReconstructionCore(coreX, coreY);

    // Live HUD stats update
    if (Math.floor(time * 10) % 15 === 0) {
      sectorCount += 256;
      frameCount += 1;
      if (hudSectors) hudSectors.textContent = sectorCount.toLocaleString() + ' LBA';
      if (hudFrames) hudFrames.textContent = frameCount + ' H.264/DHAV';
      if (hudHash && Math.floor(time) % 2 === 0) {
        hudHash.textContent = sampleHashes[Math.floor(time) % sampleHashes.length];
      }
    }

    animationFrameId = requestAnimationFrame(animate);
  }

  // Check reduced motion preference
  const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  if (!mediaQuery.matches) {
    animate();
  } else {
    time = 1;
    animate();
    cancelAnimationFrame(animationFrameId);
  }
})();
