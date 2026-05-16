const state = {
  sessionToken: localStorage.getItem("urbe_session") || "",
  user: null,
  payments: null,
  movies: [],
  listings: [],
  shares: [],
  transactions: []
};

const API_BASE_URL = window.location.protocol === "file:" ? "http://localhost:3000" : "";

const refs = {
  registerForm: document.querySelector("#register-form"),
  loginForm: document.querySelector("#login-form"),
  logoutBtn: document.querySelector("#logout-btn"),
  sessionStatus: document.querySelector("#session-status"),
  authCard: document.querySelector("#auth-card"),
  producerCard: document.querySelector("#producer-card"),
  movieForm: document.querySelector("#movie-form"),
  moviesGrid: document.querySelector("#movies-grid"),
  marketGrid: document.querySelector("#market-grid"),
  portfolioCard: document.querySelector("#portfolio-card"),
  sharesGrid: document.querySelector("#shares-grid"),
  transactionsCard: document.querySelector("#transactions-card"),
  transactionsGrid: document.querySelector("#transactions-grid"),
  toast: document.querySelector("#toast"),
  playerDialog: document.querySelector("#player-dialog"),
  playerFrame: document.querySelector("#player-frame"),
  playerTitle: document.querySelector("#player-title")
};

const actionHandlers = {
  "buy-primary": (button) => buyPrimary(button.dataset.movieId),
  "buy-listing": (button) => buyListing(button.dataset.listingId),
  "create-listing": (button) => createListing(button.dataset.shareId),
  "cancel-listing": (button) => cancelListing(button.dataset.listingId),
  "consume-token": (button) => consumeToken(button.dataset.token, button.dataset.movieTitle)
};

function escapeHtml(text) {
  return String(text || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatPriceFromCents(cents) {
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL"
  }).format((Number(cents) || 0) / 100);
}

function badgeForState(state) {
  const map = {
    available: { cls: "ok", label: "Disponível" },
    reserved: { cls: "warn", label: "Reservada" },
    owned: { cls: "ok", label: "Ativa" },
    listed: { cls: "warn", label: "Anunciada" },
    consumed: { cls: "fail", label: "Consumida" }
  };

  return map[state] || { cls: "", label: state };
}

function normalizeCast(castValue) {
  const source = Array.isArray(castValue) ? castValue : String(castValue || "").split(",");
  return source
    .map((entry) => String(entry || "").trim())
    .filter(Boolean);
}

function castLabel(castValue) {
  const cast = normalizeCast(castValue);
  return cast.length ? cast.join(", ") : "Não informado";
}

function safeExternalUrl(urlValue) {
  const raw = String(urlValue || "").trim();
  if (!raw) return "";

  try {
    const parsed = new URL(raw);
    if (!["http:", "https:"].includes(parsed.protocol)) {
      return "";
    }
    return parsed.toString();
  } catch {
    return "";
  }
}

function formatDurationMinutes(value) {
  const parsed = Number.parseInt(String(value || "").trim(), 10);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    return "Não informado";
  }

  const hours = Math.floor(parsed / 60);
  const minutes = parsed % 60;
  if (!hours) {
    return `${minutes} min`;
  }

  return `${hours}h ${minutes.toString().padStart(2, "0")}min`;
}

function notify(message, isError = false) {
  refs.toast.textContent = message;
  refs.toast.style.borderColor = isError ? "rgba(255, 93, 109, 0.55)" : "rgba(255,255,255,0.16)";
  refs.toast.classList.add("show");

  clearTimeout(notify._timer);
  notify._timer = setTimeout(() => refs.toast.classList.remove("show"), 2600);
}

async function api(path, { method = "GET", body } = {}) {
  const headers = {};
  const normalizedPath = String(path || "").startsWith("/") ? path : `/${String(path || "")}`;
  const url = `${API_BASE_URL}${normalizedPath}`;

  if (state.sessionToken) {
    headers.Authorization = `Bearer ${state.sessionToken}`;
  }

  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  let response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined
    });
  } catch {
    if (window.location.protocol === "file:") {
      throw new Error("Não foi possível conectar à API. Execute npm start e mantenha http://localhost:3000 ativo.");
    }
    throw new Error("Falha de conexão com a API.");
  }

  let payload = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }

  if (!response.ok) {
    throw new Error(payload.error || `Erro ${response.status}`);
  }

  return payload;
}

function setSession(token, user) {
  state.sessionToken = token || "";
  state.user = user || null;

  if (token) {
    localStorage.setItem("urbe_session", token);
  } else {
    localStorage.removeItem("urbe_session");
  }

  renderSession();
}

function renderSession() {
  if (!state.user) {
    refs.sessionStatus.textContent = "Não autenticado";
    refs.logoutBtn.hidden = true;
    refs.producerCard.hidden = true;
    refs.portfolioCard.hidden = true;
    refs.transactionsCard.hidden = true;
    return;
  }

  refs.sessionStatus.textContent = `Conectado: ${state.user.name}`;
  refs.logoutBtn.hidden = false;
  refs.producerCard.hidden = false;
  refs.portfolioCard.hidden = false;
  refs.transactionsCard.hidden = false;
}

function renderMovies() {
  if (!state.movies.length) {
    refs.moviesGrid.innerHTML = '<p>Nenhum filme cadastrado ainda.</p>';
    return;
  }

  refs.moviesGrid.innerHTML = state.movies
    .map((movie) => {
      const canBuy = state.user && movie.stats.primaryAvailable > 0;
      const trailerUrl = safeExternalUrl(movie.trailerUrl);
      const coverImageUrl = safeExternalUrl(movie.coverImageUrl);
      const buyBtn = canBuy
        ? `<button data-action=\"buy-primary\" data-movie-id=\"${movie.id}\">Comprar cota primária</button>`
        : "";

      return `
        <article class=\"item item-movie\">
          <small class=\"item-kicker\">Feature Drop</small>
          ${coverImageUrl ? `<img class=\"movie-cover\" src=\"${escapeHtml(coverImageUrl)}\" alt=\"Capa de ${escapeHtml(movie.title)}\" loading=\"lazy\" />` : ""}
          <strong>${escapeHtml(movie.title)}</strong>
          <small>${escapeHtml(movie.description || "Sem descrição")}</small>
          <small>Gênero: ${escapeHtml(movie.genre || "Não informado")}</small>
          <small>Duração: ${formatDurationMinutes(movie.durationMinutes)}</small>
          <small>Direção: ${escapeHtml(movie.director || "Não informado")}</small>
          <small>Ano: ${movie.releaseYear || "Não informado"}</small>
          <small>Elenco: ${escapeHtml(castLabel(movie.cast))}</small>
          ${
            trailerUrl
              ? `<a class=\"trailer-link\" href=\"${escapeHtml(trailerUrl)}\" target=\"_blank\" rel=\"noopener noreferrer\">Assistir trailer</a>`
              : "<small>Trailer: não informado</small>"
          }
          <small>Produtor: ${escapeHtml(movie.producer?.name || "-")}</small>
          <small>Preço primário: ${formatPriceFromCents(movie.priceCents)}</small>
          <small>Cotas totais: ${movie.totalShares}</small>
          <small>Primário disponível: ${movie.stats.primaryAvailable}</small>
          <small>Reservadas em checkout: ${movie.stats.reservedPrimary || 0}</small>
          <small>Mercado ativo: ${movie.stats.listed}</small>
          <small>Consumidas: ${movie.stats.consumed}</small>
          ${buyBtn}
        </article>
      `;
    })
    .join("");
}

function renderListings() {
  if (!state.listings.length) {
    refs.marketGrid.innerHTML = '<p>Sem ofertas de revenda no momento.</p>';
    return;
  }

  refs.marketGrid.innerHTML = state.listings
    .map((listing) => {
      const canBuy = state.user && listing.sellerId !== state.user.id;
      const trailerUrl = safeExternalUrl(listing.movie?.trailerUrl);
      const coverImageUrl = safeExternalUrl(listing.movie?.coverImageUrl);
      return `
        <article class=\"item item-market\">
          <small class=\"item-kicker\">Secondary Offer</small>
          ${coverImageUrl ? `<img class=\"movie-cover\" src=\"${escapeHtml(coverImageUrl)}\" alt=\"Capa de ${escapeHtml(listing.movie?.title || "Filme")}\" loading=\"lazy\" />` : ""}
          <strong>${escapeHtml(listing.movie?.title || "Filme")}</strong>
          <small>Gênero: ${escapeHtml(listing.movie?.genre || "Não informado")}</small>
          <small>Duração: ${formatDurationMinutes(listing.movie?.durationMinutes)}</small>
          <small>Direção: ${escapeHtml(listing.movie?.director || "Não informado")}</small>
          <small>Ano: ${listing.movie?.releaseYear || "Não informado"}</small>
          <small>Elenco: ${escapeHtml(castLabel(listing.movie?.cast))}</small>
          ${
            trailerUrl
              ? `<a class=\"trailer-link\" href=\"${escapeHtml(trailerUrl)}\" target=\"_blank\" rel=\"noopener noreferrer\">Assistir trailer</a>`
              : "<small>Trailer: não informado</small>"
          }
          <small>Anúncio: ${listing.id}</small>
          <small>Vendedor: ${escapeHtml(listing.seller?.name || "-")}</small>
          <small>Preço: ${formatPriceFromCents(listing.priceCents)}</small>
          ${canBuy ? `<button data-action=\"buy-listing\" data-listing-id=\"${listing.id}\">Comprar anúncio</button>` : ""}
        </article>
      `;
    })
    .join("");
}

function renderShares() {
  if (!state.user) {
    refs.sharesGrid.innerHTML = '<p>Faça login para ver suas cotas.</p>';
    return;
  }

  if (!state.shares.length) {
    refs.sharesGrid.innerHTML = '<p>Você ainda não possui cotas.</p>';
    return;
  }

  refs.sharesGrid.innerHTML = state.shares
    .map((share) => {
      const badge = badgeForState(share.state);
      const token = share.activeToken?.token;
      const tokenLine = token
        ? `<small>Token ativo: <code>${escapeHtml(token)}</code></small>`
        : "<small>Token ativo: não disponível</small>";

      const actions = [];
      if (share.state === "owned" && token) {
        actions.push(
          `<button data-action=\"consume-token\" data-token=\"${token}\" data-movie-title=\"${escapeHtml(share.movie?.title || "Filme")}\">Assistir</button>`
        );
        actions.push(`<button class=\"ghost\" data-action=\"create-listing\" data-share-id=\"${share.id}\">Anunciar revenda</button>`);
      }

      if (share.state === "listed" && share.activeListing?.id) {
        actions.push(
          `<button class=\"ghost\" data-action=\"cancel-listing\" data-listing-id=\"${share.activeListing.id}\">Cancelar anúncio</button>`
        );
      }

      return `
        <article class=\"item item-share\">
          <small class=\"item-kicker\">My Position</small>
          <strong>${escapeHtml(share.movie?.title || "Filme")}</strong>
          <span class=\"badge ${badge.cls}\">${badge.label}</span>
          <small>Cota: ${share.id}</small>
          ${tokenLine}
          ${
            share.activeListing
              ? `<small>Anúncio ${share.activeListing.status === "reserved" ? "reservado em checkout" : "ativo"}: ${formatPriceFromCents(share.activeListing.priceCents)}</small>`
              : ""
          }
          <div class=\"inline\">${actions.join("")}</div>
        </article>
      `;
    })
    .join("");
}

function renderTransactions() {
  if (!state.user) {
    refs.transactionsGrid.innerHTML = '<p>Faça login para ver transações.</p>';
    return;
  }

  if (!state.transactions.length) {
    refs.transactionsGrid.innerHTML = '<p>Sem transações registradas.</p>';
    return;
  }

  refs.transactionsGrid.innerHTML = state.transactions
    .map(
      (txn) => `
      <article class=\"item item-transaction\">
        <small class=\"item-kicker\">Ledger Event</small>
        <strong>${escapeHtml(txn.movieTitle)}</strong>
        <small>Tipo: ${escapeHtml(txn.type)}</small>
        <small>Valor: ${formatPriceFromCents(txn.priceCents)}</small>
        <small>Quando: ${new Date(txn.createdAt).toLocaleString("pt-BR")}</small>
      </article>
    `
    )
    .join("");
}

function renderAll() {
  renderSession();
  renderMovies();
  renderListings();
  renderShares();
  renderTransactions();
}

async function refreshData() {
  const [moviesResp, listingsResp, paymentsResp] = await Promise.all([
    api("/api/movies"),
    api("/api/listings"),
    api("/api/payments/config")
  ]);
  state.movies = moviesResp.movies || [];
  state.listings = listingsResp.listings || [];
  state.payments = paymentsResp.payments || null;

  if (state.user) {
    const [sharesResp, txResp] = await Promise.all([api("/api/me/shares"), api("/api/me/transactions")]);
    state.shares = sharesResp.shares || [];
    state.transactions = txResp.transactions || [];
  } else {
    state.shares = [];
    state.transactions = [];
  }

  renderAll();
}

function clearCheckoutQueryParams() {
  const url = new URL(window.location.href);
  const shouldClear = url.searchParams.has("checkout") || url.searchParams.has("orderId") || url.searchParams.has("session_id");

  if (!shouldClear) return;

  url.searchParams.delete("checkout");
  url.searchParams.delete("orderId");
  url.searchParams.delete("session_id");
  window.history.replaceState({}, "", url.toString());
}

async function handleCheckoutReturn() {
  const url = new URL(window.location.href);
  const checkoutState = url.searchParams.get("checkout");
  const orderId = url.searchParams.get("orderId");
  const sessionId = url.searchParams.get("session_id");

  if (!checkoutState || !orderId) {
    return;
  }

  if (!state.user) {
    notify("Faça login para validar o retorno do checkout.", true);
    return;
  }

  if (checkoutState === "cancel") {
    try {
      await api(`/api/payments/orders/${orderId}/cancel`, { method: "POST", body: {} });
      notify("Checkout cancelado. Reserva liberada.");
    } catch (error) {
      notify(error.message, true);
    }
    return;
  }

  if (checkoutState === "success") {
    try {
      await api(`/api/payments/orders/${orderId}/confirm`, {
        method: "POST",
        body: { sessionId: sessionId || undefined }
      });
      notify("Pagamento confirmado e cota transferida.");
    } catch (error) {
      notify(error.message, true);
    }
  }
}

async function bootstrapSession() {
  if (!state.sessionToken) {
    renderAll();
    await refreshData();
    return;
  }

  try {
    const me = await api("/api/auth/me");
    setSession(state.sessionToken, me.user);
  } catch {
    setSession("", null);
  }

  await handleCheckoutReturn();
  await refreshData();
  clearCheckoutQueryParams();
}

async function register(event) {
  event.preventDefault();
  const formData = new FormData(event.currentTarget);
  const payload = Object.fromEntries(formData.entries());

  try {
    const response = await api("/api/auth/register", { method: "POST", body: payload });
    setSession(response.sessionToken, response.user);
    await handleCheckoutReturn();
    clearCheckoutQueryParams();
    notify("Conta criada e sessão iniciada.");
    event.currentTarget.reset();
    await refreshData();
  } catch (error) {
    notify(error.message, true);
  }
}

async function login(event) {
  event.preventDefault();
  const formData = new FormData(event.currentTarget);
  const payload = Object.fromEntries(formData.entries());

  try {
    const response = await api("/api/auth/login", { method: "POST", body: payload });
    setSession(response.sessionToken, response.user);
    await handleCheckoutReturn();
    clearCheckoutQueryParams();
    notify("Login realizado.");
    event.currentTarget.reset();
    await refreshData();
  } catch (error) {
    notify(error.message, true);
  }
}

async function logout() {
  try {
    await api("/api/auth/logout", { method: "POST" });
  } catch {
    // Silêncio: sessão pode já estar inválida.
  }

  setSession("", null);
  notify("Sessão encerrada.");
  await refreshData();
}

async function createMovie(event) {
  event.preventDefault();

  const formData = new FormData(event.currentTarget);
  const payload = {
    title: formData.get("title"),
    description: formData.get("description"),
    director: formData.get("director"),
    coverImageUrl: formData.get("coverImageUrl"),
    genre: formData.get("genre"),
    durationMinutes: formData.get("durationMinutes") ? Number(formData.get("durationMinutes")) : undefined,
    releaseYear: formData.get("releaseYear") ? Number(formData.get("releaseYear")) : undefined,
    trailerUrl: formData.get("trailerUrl"),
    cast: formData.get("cast"),
    priceCents: Number(formData.get("priceCents")),
    totalShares: Number(formData.get("totalShares")),
    bunnyVideoId: formData.get("bunnyVideoId"),
    bunnyLibraryId: formData.get("bunnyLibraryId") || undefined
  };

  try {
    await api("/api/movies", { method: "POST", body: payload });
    notify("Filme cadastrado com sucesso.");
    event.currentTarget.reset();
    await refreshData();
  } catch (error) {
    notify(error.message, true);
  }
}

async function buyPrimary(movieId) {
  if (!state.user) {
    notify("Faça login para comprar cotas.", true);
    return;
  }

  const movie = state.movies.find((item) => item.id === movieId);
  const movieTitle = movie ? movie.title : "Cota";

  try {
    const response = await api(`/api/payments/primary/${movieId}/checkout`, { method: "POST", body: {} });

    if (response.checkout?.provider === "openpix") {
      mostrarModalPix({ order: response.order, checkout: response.checkout }, movieTitle);
      return;
    }

    if (response.purchase) {
      notify("Pagamento aprovado. Cota comprada no mercado primário.");
      await refreshData();
      return;
    }

    if (response.checkout?.checkoutUrl) {
      notify("Redirecionando para checkout seguro...");
      window.location.href = response.checkout.checkoutUrl;
      return;
    }

    if (response.order?.id) {
      await api(`/api/payments/orders/${response.order.id}/confirm`, {
        method: "POST",
        body: { sessionId: response.checkout?.sessionId || undefined }
      });
      notify("Pagamento confirmado. Cota comprada.");
    }

    await refreshData();
  } catch (error) {
    notify(error.message, true);
  }
}

async function buyListing(listingId) {
  if (!state.user) {
    notify("Faça login para comprar no mercado secundário.", true);
    return;
  }

  const listing = state.listings.find((item) => item.id === listingId);
  const movieTitle = listing?.movie?.title || "Cota";

  try {
    const response = await api(`/api/payments/listings/${listingId}/checkout`, { method: "POST", body: {} });

    if (response.checkout?.provider === "openpix") {
      mostrarModalPix({ order: response.order, checkout: response.checkout }, movieTitle);
      return;
    }

    if (response.purchase) {
      notify("Pagamento aprovado. Compra de revenda concluída com novo token.");
      await refreshData();
      return;
    }

    if (response.checkout?.checkoutUrl) {
      notify("Redirecionando para checkout seguro...");
      window.location.href = response.checkout.checkoutUrl;
      return;
    }

    if (response.order?.id) {
      await api(`/api/payments/orders/${response.order.id}/confirm`, {
        method: "POST",
        body: { sessionId: response.checkout?.sessionId || undefined }
      });
      notify("Pagamento confirmado. Revenda concluída.");
    }

    await refreshData();
  } catch (error) {
    notify(error.message, true);
  }
}

async function createListing(shareId) {
  const value = window.prompt("Preço da revenda em centavos (ex: 2500):", "2500");
  if (!value) return;

  try {
    await api(`/api/shares/${shareId}/listings`, {
      method: "POST",
      body: { priceCents: Number(value) }
    });
    notify("Cota anunciada no mercado secundário.");
    await refreshData();
  } catch (error) {
    notify(error.message, true);
  }
}

async function cancelListing(listingId) {
  try {
    await api(`/api/listings/${listingId}/cancel`, { method: "POST", body: {} });
    notify("Anúncio cancelado.");
    await refreshData();
  } catch (error) {
    notify(error.message, true);
  }
}

async function consumeToken(token, movieTitle) {
  try {
    const response = await api("/api/access/consume", { method: "POST", body: { token } });
    const playbackUrl = response.playback.watchUrl || response.playback.watchPath || response.playback.embedUrl;

    if (!playbackUrl) {
      throw new Error("Não foi possível gerar o link de reprodução.");
    }

    refs.playerTitle.textContent = `${movieTitle} | visualização única`;
    refs.playerFrame.src = playbackUrl;
    refs.playerDialog.showModal();

    notify("Token consumido. Visualização liberada.");
    await refreshData();
  } catch (error) {
    notify(error.message, true);
  }
}

// ==================== FUNÇÕES PIX ====================
let pixOrderId = "";
let pixSessionId = "";
let pixTimerInterval = null;

function mostrarModalPix(payload, movieTitle) {
  const order = payload?.order || payload || {};
  const checkout = payload?.checkout || payload || {};

  pixOrderId = order.id || payload?.orderId || payload?.id || "";
  pixSessionId = checkout.sessionId || payload?.sessionId || "";

  const qrCodeRaw = checkout.qrCodeBase64 || payload?.qrCodeBase64 || "";
  const qrCodeSrc = qrCodeRaw && !qrCodeRaw.startsWith("data:") ? `data:image/png;base64,${qrCodeRaw}` : qrCodeRaw;

  document.getElementById("pixMovieTitle").textContent = movieTitle || "Cota de visualização";
  document.getElementById("pixQrCode").src = qrCodeSrc;
  document.getElementById("pixCopiaCola").value = checkout.pixCopiaECola || payload?.pixCopiaECola || "";

  if (!pixOrderId || !qrCodeSrc) {
    notify("Não foi possível preparar o checkout Pix.", true);
    return;
  }

  // Timer de 15 minutos
  let timeLeft = 15 * 60;
  const timerEl = document.getElementById("pixTimer");

  if (pixTimerInterval) clearInterval(pixTimerInterval);
  pixTimerInterval = setInterval(() => {
    timeLeft--;
    const min = Math.floor(timeLeft / 60);
    const sec = timeLeft % 60;
    timerEl.textContent = `${min}:${sec < 10 ? "0" : ""}${sec}`;
    if (timeLeft <= 0) {
      clearInterval(pixTimerInterval);
      timerEl.textContent = "EXPIRADO";
    }
  }, 1000);

  document.getElementById("pixModal").hidden = false;
}

function copiarPix() {
  const input = document.getElementById("pixCopiaCola");
  if (!input?.value) {
    notify("Código Pix indisponível.", true);
    return;
  }

  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(input.value).then(
      () => notify("✅ Código Pix copiado!"),
      () => notify("Não foi possível copiar o código Pix.", true)
    );
    return;
  }

  input.select();
  document.execCommand("copy");
  notify("✅ Código Pix copiado!");
}

function fecharPixModal() {
  document.getElementById("pixModal").hidden = true;
  if (pixTimerInterval) clearInterval(pixTimerInterval);
  pixOrderId = "";
  pixSessionId = "";
}

async function verificarPagamentoPix() {
  if (!pixOrderId) return;
  try {
    const data = await api(`/api/payments/orders/${pixOrderId}/confirm`, {
      method: "POST",
      body: { sessionId: pixSessionId || undefined }
    });
    const isPaid = Boolean(data.purchase) || Boolean(data.alreadyPaid) || data.order?.status === "paid";

    if (isPaid) {
      notify("🎉 Pagamento confirmado! Token liberado.");
      fecharPixModal();
      await refreshData();
      return;
    }

    notify("⏳ Ainda não detectamos o pagamento. Tente novamente em alguns segundos.");
  } catch (error) {
    notify(error?.message || "Erro ao verificar pagamento", true);
  }
}

function bindGlobalActions() {
  document.body.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;

    const actionName = target.dataset.action;
    if (!actionName || !actionHandlers[actionName]) return;

    await actionHandlers[actionName](target);
  });

  refs.playerDialog.addEventListener("close", () => {
    refs.playerFrame.src = "";
  });
}

function bindForms() {
  refs.registerForm.addEventListener("submit", register);
  refs.loginForm.addEventListener("submit", login);
  refs.logoutBtn.addEventListener("click", logout);
  refs.movieForm.addEventListener("submit", createMovie);
}

bindGlobalActions();
bindForms();
bootstrapSession().catch((error) => {
  console.error(error);
  notify(error?.message || "Falha ao inicializar a aplicação.", true);
});