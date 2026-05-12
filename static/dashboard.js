/* =========================
   UTILIDADES DE TEMPO
========================= */

function horaParaSegundos(hora) {
  if (!hora) return null;
  const [h, m, s] = hora.split(':').map(Number);
  if ([h, m, s].some(Number.isNaN)) return null;
  return h * 3600 + m * 60 + s;
}

function ordenarPorHora(series) {
  return [...series]
    .filter(d => d && d.hora && typeof d.preco === 'number')
    .sort((a, b) => horaParaSegundos(a.hora) - horaParaSegundos(b.hora));
}

/* =========================
   RENDERIZAÇÃO DO GRÁFICO
========================= */

function renderChart(containerId, series, baseColor) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const sorted = ordenarPorHora(series);

  // Janela visual fixa (estabilidade)
  const MAX_POINTS = 20;
  const data = sorted.slice(-MAX_POINTS);

  // Se não há dados suficientes, não desenha gráfico
  if (data.length === 0) {
    Plotly.react(container, [], {
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      xaxis: { visible: false },
      yaxis: { visible: false },
      annotations: [{
        text: 'Aguardando dados…',
        x: 0.5,
        y: 0.5,
        xref: 'paper',
        yref: 'paper',
        showarrow: false,
        font: { color: '#94a3b8', size: 12 }
      }]
    }, { responsive: true });
    return;
  }

  const lastIndex = data.length - 1;
  const last = data[lastIndex];
  const prev = data[lastIndex - 1];

  const delta = last.preco - prev.preco;
  const directionColor = delta >= 0
    ? 'rgba(34,197,94,0.9)'
    : 'rgba(239,68,68,0.9)';

  const xValues = data.map(d => d.hora);
  const yValues = data.map(d => d.preco);

  // Trace único: linha + último ponto
  const trace = {
    x: xValues,
    y: yValues,
    type: 'scatter',
    mode: 'lines+markers',

    line: {
      color: baseColor,
      width: 2,
      shape: 'spline'
    },

    marker: {
      size: data.map((_, i) => i === lastIndex ? 6 : 0),
      color: data.map((_, i) =>
        i === lastIndex ? directionColor : 'rgba(0,0,0,0)'
      ),
      line: {
        color: '#e5e7eb',
        width: 1
      }
    },

    hovertemplate:
      'Preço: R$ %{y}<br>' +
      'Horário: %{x}<extra></extra>',

    showlegend: false
  };

  // Estabilização do eixo Y
  const min = Math.min(...yValues);
  const max = Math.max(...yValues);
  const pad = (max - min) * 0.3 || min * 0.001;

  const layout = {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',

    margin: { t: 10, l: 48, r: 20, b: 36 },

    font: {
      color: 'rgba(148,163,184,0.85)',
      size: 11
    },

    xaxis: {
      type: 'category',
      categoryorder: 'array',
      categoryarray: xValues,
      showgrid: true,
      gridcolor: 'rgba(148,163,184,0.15)',
      linecolor: 'rgba(148,163,184,0.25)',
      tickfont: { size: 10 },
      automargin: true
    },

    yaxis: {
      autorange: false,
      range: [min - pad, max + pad],
      showgrid: true,
      gridcolor: 'rgba(148,163,184,0.15)',
      linecolor: 'rgba(148,163,184,0.25)',
      tickfont: { size: 10 },
      automargin: true
    },

    shapes: [{
      type: 'line',
      xref: 'paper',
      x0: 0,
      x1: 1,
      yref: 'y',
      y0: last.preco,
      y1: last.preco,
      line: {
        color: 'rgba(148,163,184,0.35)',
        width: 1,
        dash: 'dot'
      }
    }]
  };

  Plotly.react(container, [trace], layout, { responsive: true });

  // Realce visual do card (opcional)
  const card = container.closest('.chart-card');
  if (card) {
    card.style.borderColor = directionColor;
  }
}

/* =========================
   ATUALIZAÇÃO GLOBAL
========================= */

function atualizarDashboard() {
  fetch('/dados_atualizados')
    .then(r => r.json())
    .then(d => {
      renderChart('chart-usd', d.dolar, 'rgba(56,189,248,0.85)');
      renderChart('chart-btc', d.btc,   'rgba(245,158,11,0.85)');
      renderChart('chart-eth', d.eth,   'rgba(139,92,246,0.85)');
      renderChart('chart-sol', d.sol,   'rgba(34,197,94,0.85)');
    })
    .catch(err => console.error('Erro ao atualizar dashboard:', err));
}

atualizarDashboard();
setInterval(atualizarDashboard, 30000);

async function enviarComandoControle(endpoint, mensagemConfirmacao) {
  const confirmou = confirm(mensagemConfirmacao);

  if (!confirmou) {
    return;
  }

  const token = prompt("Digite o token de controle:");

  if (!token) {
    alert("Operação cancelada: token vazio.");
    return;
  }

  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Control-Token": token
      },
      body: JSON.stringify({
        source: "dashboard"
      })
    });

    const data = await response.json();

    if (!response.ok || !data.ok) {
      alert(`Erro: ${data.error || "falha desconhecida"}`);
      return;
    }

    alert(data.message || "Comando executado com sucesso.");

  } catch (error) {
    console.error("Erro ao enviar comando:", error);
    alert("Erro ao enviar comando de controle.");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const btnStop = document.getElementById("btn-stop-monitor");
  const btnExit = document.getElementById("btn-exit-process");

  if (btnStop) {
    btnStop.addEventListener("click", () => {
      enviarComandoControle(
        "/api/shutdown_monitor",
        "Deseja pausar o monitoramento? O site continuará aberto."
      );
    });
  }

  if (btnExit) {
    btnExit.addEventListener("click", () => {
      enviarComandoControle(
        "/api/exit_process",
        "ATENÇÃO: isso encerrará o processo inteiro e liberará a porta. Continuar?"
      );
    });
  }
});