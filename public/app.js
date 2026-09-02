const VIEW_IDS = ["catalog", "market", "portfolio", "publish", "account"];

const state = {
  sessionToken: localStorage.getItem("urbe_session") || "",
  user: null,
  payments: null,
  movies: [],
  listings: [],
  shares: [],
  transactions: [],
  orders: [],
  bunny: null,
  view: "catalog",
  search: "",
  genre: "",
  pendingAction: null,
  loading: false,
  listingShareId: "",
  confirmAction: null
};

const API_BASE_URL = window.location.protocol === "file:" ? "http://localhost:3000" : "";

const refs = {
  progress: document.querySelector("#progress"),
  sessionStatus: document.querySelector("#session-status"),
  loginBtn: document.querySelector("#login-btn"),
  logoutBtn: document.querySelector("#logout-btn"),
  sharesCount: document.querySelector("#shares-count"),
  moviesGrid: document.querySelector("#movies-grid"),
  marketGrid: document.querySelector("#market-grid"),
  sharesGrid: document.querySelector("#shares-grid"),
  transactionsGrid: document.querySelector("#transactions-grid"),
  pendingBanner: document.querySelector("#pending-banner"),
  movieSearch: document.querySelector("#movie-search"),
  movieGenre: document.querySelector("#movie-genre"),
  movieForm: document.querySelector("#movie-form"),
  priceHint: document.querySelector("#price-hint"),
  registerForm: document.querySelector("#register-form"),
  loginForm: document.querySelector("#login-form"),
  accountCopy: document.querySelector("#account-copy"),
  toast: document.querySelector("#toast"),
  listingDialog: document.querySelector("#listing-dialog"),
  listingForm: document.querySelector("#listing-form"),
  listingMovieTitle: document.querySelector("#listing-movie-title"),
  listingPrice: document.querySelector("#listing-price"),
  confirmDialog: document.querySelector("#confirm-dialog"),
  confirmForm: document.querySelector("#confirm-form"),
  confirmTitle: document.querySelector("#confirm-title"),
  confirmCopy: document.querySelector("#confirm-copy"),
  confirmAccept: document.querySelector("#confirm-accept"),
  pixDialog: document.querySelector("#pix-dialog"),
  pixMovieTitle: document.querySelector("#pixMovieTitle"),
  pixQrCode: document.querySelector("#pixQrCode"),
  pixCopiaCola: document.querySelector("#pixCopiaCola"),
  pixCopyBtn: document.querySelector("#pix-copy-btn"),
  pixCheckBtn: document.querySelector("#pix-check-btn"),
  pixTimer: document.querySelector("#pixTimer"),
  playerDialog: document.querySelector("#player-dialog"),
  playerFrame: document.querySelector("#player-frame"),
  playerTitle: document.querySelector("#player-title"),
  playerStatus: document.querySelector("#player-status"),
  bunnyStatusCopy: document.querySelector("#bunny-status-copy"),
  bunnyCreateBtn: document.querySelector("#bunny-create-btn"),
  bunnyHint: document.querySelector("#bunny-hint")
};

const actionHandlers = {
  "buy-primary": (button) => requestPrimaryPurchase(button.dataset.movieId),
  "buy-listing": (button) => requestListingPurchase(button.dataset.listingId),
  "create-listing": (button) => openListingDialog(button.dataset.shareId),
  "cancel-listing": (button) => cancelListing(button.dataset.listingId),
  "consume-token": (button) => confirmWatch(button.dataset.token, button.dataset.movieTitle, button.dataset.shareId),
  "resume-playback": (button) => resumeWatch(button.dataset.shareId, button.dataset.movieTitle),
  "login-to-buy": (button) => requireAuth(button.dataset.resume || "buy")
};

let pixOrderId = "";
let pixSessionId = "";
let pixTimerInterval = null;
let pixPollInterval = null;
let playbackPollInterval = null;
let playbackShareId = "";

function pixImageSrc(raw) {
  const value = String(raw || "").trim();
  if (!value) return "";
  if (/^(data:|https?:)/i.test(value)) return value;
  return `data:image/png;base64,${value}`;
}

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

function parseReaisToCents(value) {
  const raw = String(value || "")
    .trim()
    .replace(/[^\d,.-]/g, "");
  if (!raw) return NaN;

  let normalized = raw;
  if (raw.includes(",") && raw.includes(".")) {
    normalized = raw.replace(/\./g, "").replace(",", ".");
  } else if (raw.includes(",")) {
    normalized = raw.replace(",", ".");
  }

  const amount = Number(normalized);
  if (!Number.isFinite(amount) || amount <= 0) return NaN;
  return Math.round(amount * 100);
}

function centsToReaisInput(cents) {
  return ((Number(cents) || 0) / 100).toFixed(2).replace(".", ",");
}

function formatCountdown(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  const min = Math.floor(value / 60);
  const sec = value % 60;
  return `${min}:${sec.toString().padStart(2, "0")}`;
}

function tokenStory(share) {
  const ts = share.tokenState || {};
  const code = ts.code;
  const bunnyReady = Boolean(ts.bunnyReady);
  const token = share.accessToken || share.activeToken;
  const origin =
    token?.reason === "resale" ? "Token emitido na revenda." : token?.reason === "primary_purchase" ? "Token emitido na compra original." : "";
  const bunnyLine = bunnyReady
    ? "Player Bunny pronto para esta cota."
    : "Player Bunny incompleto — sem ID de vídeo o token não abre.";

  const map = {
    ready: {
      cls: "ok",
      label: "Pronta para assistir",
      tokenLabel: "Token ativo",
      detail: `1 visualização restante. ${origin} Ao abrir o player, o token é gasto.`.trim()
    },
    opening_player: {
      cls: "warn",
      label: "Abrindo player",
      tokenLabel: "Token em uso",
      detail: "Sessão Bunny em andamento. Se o player não abrir, o token volta a ficar ativo."
    },
    held_for_sale: {
      cls: "warn",
      label: "À venda",
      tokenLabel: "Token em espera",
      detail: "O token continua válido, mas assistir fica bloqueado enquanto a cota está no mercado. Se vender, este token é revogado e o comprador recebe um novo."
    },
    checkout_reserved: {
      cls: "warn",
      label: "Checkout em andamento",
      tokenLabel: "Token reservado",
      detail: "A cota está presa em um pagamento. Se o checkout expirar, ela volta para você."
    },
    used: {
      cls: "fail",
      label: "Assistida",
      tokenLabel: "Token usado",
      detail: "A visualização única já foi liberada no Bunny. Esta cota não volta ao mercado."
    },
    revoked: {
      cls: "fail",
      label: "Token revogado",
      tokenLabel: "Revogado na revenda",
      detail: "O token antigo morreu na transferência. O comprador recebeu um token novo."
    },
    missing: {
      cls: "fail",
      label: "Sem token",
      tokenLabel: "Token ausente",
      detail: "Esta cota não tem um token ativo para o player."
    }
  };
  const story = map[code] || map[share.state] || map.missing;
  const remainingViews = Number.isFinite(ts.remainingViews) ? ts.remainingViews : code === "used" || code === "revoked" || code === "missing" ? 0 : 1;
  return {
    ...story,
    cls: map[code]?.cls || story.cls,
    label: ts.label || story.label,
    tokenLabel: ts.tokenLabel || story.tokenLabel,
    detail: ts.detail || story.detail,
    bunnyLine,
    bunnyReady,
    canWatch: ts.canWatch ?? (code === "ready" && bunnyReady && Boolean(share.activeToken?.token || token?.token)),
    canResume: ts.canResume ?? code === "opening_player",
    canList: ts.canList ?? code === "ready",
    steps: Array.isArray(ts.steps) ? ts.steps : [],
    remainingViews,
    playbackRemainingSeconds: ts.playbackRemainingSeconds || share.pendingPlayback?.remainingSeconds || 0,
    code
  };
}

function tokenStepsHtml(steps) {
  if (!steps.length) return "";
  return `<ol class="token-steps">${steps
    .map((step) => `<li class="is-${escapeHtml(step.state || "todo")}">${escapeHtml(step.label)}</li>`)
    .join("")}</ol>`;
}

function transactionLabel(type) {
  const map = {
    primary_purchase: "Compra primária",
    secondary_purchase: "Revenda"
  };
  return map[type] || type || "Movimentação";
}

function normalizeCast(castValue) {
  const source = Array.isArray(castValue) ? castValue : String(castValue || "").split(",");
  return source.map((entry) => String(entry || "").trim()).filter(Boolean);
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
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.toString() : "";
  } catch {
    return "";
  }
}

function formatDurationMinutes(value) {
  const parsed = Number.parseInt(String(value || "").trim(), 10);
  if (!Number.isInteger(parsed) || parsed <= 0) return "";
  const hours = Math.floor(parsed / 60);
  const minutes = parsed % 60;
  if (!hours) return `${minutes} min`;
  return `${hours}h ${minutes.toString().padStart(2, "0")}min`;
}

function movieMatchesQuery(movie, query, genre) {
  if (genre && String(movie.genre || "") !== genre) return false;
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  const haystack = [
    movie.title,
    movie.director,
    movie.description,
    movie.genre,
    castLabel(movie.cast)
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(needle);
}

function skeletonCards(count = 3) {
  return Array.from({ length: count }, () => '<article class="item skeleton-card" aria-hidden="true"></article>').join("");
}

function setLoading(isLoading) {
  state.loading = Boolean(isLoading);
  document.body.classList.toggle("is-loading", state.loading);
  if (refs.progress) refs.progress.hidden = !state.loading;
}

async function withLoading(task) {
  if (state.loading) return null;
  setLoading(true);
  try {
    return await task();
  } finally {
    setLoading(false);
  }
}

function notify(message, isError = false) {
  refs.toast.textContent = message;
  refs.toast.classList.toggle("is-error", isError);
  refs.toast.classList.add("show");
  clearTimeout(notify._timer);
  notify._timer = setTimeout(() => refs.toast.classList.remove("show"), 3200);
}

async function api(path, { method = "GET", body } = {}) {
  const headers = {};
  const normalizedPath = String(path || "").startsWith("/") ? path : `/${String(path || "")}`;
  const url = `${API_BASE_URL}${normalizedPath}`;

  if (state.sessionToken) headers.Authorization = `Bearer ${state.sessionToken}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined
    });
  } catch {
    if (window.location.protocol === "file:") {
      throw new Error("Não foi possível conectar à API. Execute o servidor em http://localhost:3000.");
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

function currentHashView() {
  const hash = (window.location.hash || "").replace("#", "").trim();
  return VIEW_IDS.includes(hash) ? hash : "catalog";
}

function showView(viewName, { updateHash = true } = {}) {
  let nextView = VIEW_IDS.includes(viewName) ? viewName : "catalog";
  const authRequired = nextView === "portfolio" || nextView === "publish";
  if (authRequired && !state.user) {
    state.pendingAction = state.pendingAction || { type: "view", view: nextView };
    refs.accountCopy.textContent =
      nextView === "publish"
        ? "Entre para publicar um filme e emitir cotas."
        : "Entre para ver suas cotas, tokens e histórico.";
    nextView = "account";
  }

  state.view = nextView;
  document.querySelectorAll(".view").forEach((section) => {
    section.hidden = section.dataset.view !== nextView;
  });
  document.querySelectorAll("[data-nav]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.nav === nextView);
  });
  if (updateHash && currentHashView() !== nextView) {
    window.history.replaceState({}, "", `${window.location.pathname}${window.location.search}#${nextView}`);
  }
}

function requireAuth(reason) {
  refs.accountCopy.textContent =
    reason === "buy"
      ? "Entre para concluir a compra. Voltamos para o checkout em seguida."
      : "Crie uma conta ou faça login para continuar.";
  showView("account");
}

function setSession(token, user) {
  state.sessionToken = token || "";
  state.user = user || null;
  if (token) localStorage.setItem("urbe_session", token);
  else localStorage.removeItem("urbe_session");
  renderSession();
}

function renderSession() {
  const loggedIn = Boolean(state.user);
  refs.sessionStatus.textContent = loggedIn ? state.user.name : "Visitante";
  refs.logoutBtn.hidden = !loggedIn;
  refs.loginBtn.hidden = loggedIn;
  document.body.classList.toggle("is-authenticated", loggedIn);

  const ownedCount = state.shares.filter((share) => share.state === "owned" || share.state === "listed").length;
  if (loggedIn && ownedCount) {
    refs.sharesCount.hidden = false;
    refs.sharesCount.textContent = String(ownedCount);
  } else {
    refs.sharesCount.hidden = true;
  }
}

function renderGenreFilter() {
  const current = refs.movieGenre.value;
  const genres = Array.from(new Set(state.movies.map((movie) => movie.genre).filter(Boolean))).sort();
  refs.movieGenre.innerHTML =
    '<option value="">Todos os gêneros</option>' +
    genres.map((genre) => `<option value="${escapeHtml(genre)}">${escapeHtml(genre)}</option>`).join("");
  if (genres.includes(current)) refs.movieGenre.value = current;
}

function movieMetaLine(movie) {
  return [movie.genre, formatDurationMinutes(movie.durationMinutes), movie.releaseYear]
    .filter(Boolean)
    .map((part) => escapeHtml(String(part)))
    .join(" · ");
}

function movieExtras(movie) {
  const trailerUrl = safeExternalUrl(movie.trailerUrl);
  return `
    <details class="movie-extra">
      <summary>Ficha técnica</summary>
      <small>Direção: ${escapeHtml(movie.director || "Não informado")}</small>
      <small>Elenco: ${escapeHtml(castLabel(movie.cast))}</small>
      ${
        trailerUrl
          ? `<a class="trailer-link" href="${escapeHtml(trailerUrl)}" target="_blank" rel="noopener noreferrer">Assistir trailer</a>`
          : ""
      }
    </details>
  `;
}

function renderMovies() {
  const filtered = state.movies.filter((movie) => movieMatchesQuery(movie, state.search, state.genre));
  if (!state.movies.length) {
    refs.moviesGrid.innerHTML =
      '<div class="empty-state"><strong>Catálogo ainda vazio</strong><p>Publique o primeiro filme para abrir as cotas de estreia.</p></div>';
    return;
  }
  if (!filtered.length) {
    refs.moviesGrid.innerHTML =
      '<div class="empty-state"><strong>Nenhum filme encontrado</strong><p>Ajuste a busca ou o gênero para ver outros lançamentos.</p></div>';
    return;
  }

  refs.moviesGrid.innerHTML = filtered
    .map((movie) => {
      const coverImageUrl = safeExternalUrl(movie.coverImageUrl);
      const available = Number(movie.stats?.primaryAvailable || 0);
      const canBuy = available > 0;
      let buyAction = "buy-primary";
      let buyLabel = "Comprar cota";
      let buyDisabled = false;
      if (!canBuy) {
        buyLabel = "Esgotado";
        buyDisabled = true;
      } else if (!state.user) {
        buyAction = "login-to-buy";
        buyLabel = "Entrar para comprar";
      }
      return `
        <article class="item item-movie">
          ${coverImageUrl ? `<img class="movie-cover" src="${escapeHtml(coverImageUrl)}" alt="Capa de ${escapeHtml(movie.title)}" loading="lazy" />` : `<div class="movie-cover movie-cover-fallback" aria-hidden="true"></div>`}
          <small class="item-kicker">${escapeHtml(movie.genre || "Feature Drop")}</small>
          <strong>${escapeHtml(movie.title)}</strong>
          <small class="item-meta">${movieMetaLine(movie) || "Ficha em atualização"}</small>
          <p class="price-tag">${formatPriceFromCents(movie.priceCents)}</p>
          <small>${available} ${available === 1 ? "cota disponível" : "cotas disponíveis"} · ${movie.stats?.listed || 0} no mercado</small>
          <small class="bunny-line">${movie.bunnyVideoId ? "Player Bunny ligado a este filme" : "Este filme ainda não tem player Bunny"}</small>
          <button data-action="${buyAction}" data-movie-id="${movie.id}" data-resume="buy" ${buyDisabled ? "disabled" : ""}>
            ${buyLabel}
          </button>
          ${movieExtras(movie)}
        </article>
      `;
    })
    .join("");
}

function renderListings() {
  if (!state.listings.length) {
    refs.marketGrid.innerHTML =
      '<div class="empty-state"><strong>Sem ofertas agora</strong><p>Quando alguém anunciar uma cota, ela aparece aqui na hora.</p></div>';
    return;
  }

  refs.marketGrid.innerHTML = state.listings
    .map((listing) => {
      const coverImageUrl = safeExternalUrl(listing.movie?.coverImageUrl);
      const isOwn = state.user && listing.sellerId === state.user.id;
      const buyAction = state.user ? "buy-listing" : "login-to-buy";
      return `
        <article class="item item-market">
          ${coverImageUrl ? `<img class="movie-cover" src="${escapeHtml(coverImageUrl)}" alt="Capa de ${escapeHtml(listing.movie?.title || "Filme")}" loading="lazy" />` : ""}
          <small class="item-kicker">Oferta secundária</small>
          <strong>${escapeHtml(listing.movie?.title || "Filme")}</strong>
          <small class="item-meta">${movieMetaLine(listing.movie || {})}</small>
          <p class="price-tag">${formatPriceFromCents(listing.priceCents)}</p>
          <small>Vendido por ${escapeHtml(listing.seller?.name || "coletivo")}</small>
          ${
            isOwn
              ? "<small>Este anúncio é seu</small>"
              : `<button data-action="${buyAction}" data-listing-id="${listing.id}" data-resume="buy">${state.user ? "Comprar anúncio" : "Entrar para comprar"}</button>`
          }
          ${movieExtras(listing.movie || {})}
        </article>
      `;
    })
    .join("");
}

function renderShares() {
  if (!state.user) {
    refs.sharesGrid.innerHTML = '<div class="empty-state"><strong>Entre para ver suas cotas</strong></div>';
    return;
  }
  if (!state.shares.length) {
    refs.sharesGrid.innerHTML =
      '<div class="empty-state"><strong>Você ainda não tem cotas</strong><p>Compre no catálogo ou no mercado secundário. O token chega na hora e só é gasto quando o player Bunny abre.</p></div>';
    return;
  }

  refs.sharesGrid.innerHTML = state.shares
    .map((share) => {
      const story = tokenStory(share);
      const token = share.activeToken?.token || (share.tokenState?.code === "ready" ? share.accessToken?.token : "");
      const actions = [];
      if (story.canResume) {
        actions.push(
          `<button data-action="resume-playback" data-share-id="${share.id}" data-movie-title="${escapeHtml(share.movie?.title || "Filme")}">Continuar no player Bunny</button>`
        );
      }
      if (story.canWatch && token) {
        actions.push(
          `<button data-action="consume-token" data-token="${escapeHtml(token)}" data-share-id="${share.id}" data-movie-title="${escapeHtml(share.movie?.title || "Filme")}">Assistir no Bunny</button>`
        );
      } else if (share.tokenState?.code === "ready" && !story.bunnyReady) {
        actions.push(`<small class="token-block">Assistir bloqueado até o filme ter ID Bunny. O token permanece ativo.</small>`);
      }
      if (story.canList) {
        actions.push(`<button class="ghost" data-action="create-listing" data-share-id="${share.id}">Anunciar revenda</button>`);
      }
      if (share.state === "listed" && share.activeListing?.id && share.activeListing.status !== "reserved") {
        actions.push(
          `<button class="ghost" data-action="cancel-listing" data-listing-id="${share.activeListing.id}">Tirar do mercado</button>`
        );
      }
      const listingLine = share.activeListing
        ? `<small>Anúncio ${share.activeListing.status === "reserved" ? "reservado no checkout" : "ativo"}: ${formatPriceFromCents(share.activeListing.priceCents)}</small>`
        : "";
      const countdown =
        story.canResume && story.playbackRemainingSeconds
          ? `<small class="token-countdown">Sessão expira em ${formatCountdown(story.playbackRemainingSeconds)}</small>`
          : "";
      return `
        <article class="item item-share" data-share-id="${share.id}">
          <small class="item-kicker">${escapeHtml(share.movie?.genre || "Cota")}</small>
          <strong>${escapeHtml(share.movie?.title || "Filme")}</strong>
          <div class="token-status token-status-${story.cls}">
            <span class="badge ${story.cls}">${escapeHtml(story.label)}</span>
            <small class="token-line"><strong>${escapeHtml(story.tokenLabel)}</strong></small>
            <small class="token-line">${escapeHtml(story.detail)}</small>
            <small class="bunny-line">${escapeHtml(story.bunnyLine)}</small>
            ${tokenStepsHtml(story.steps)}
            ${countdown}
          </div>
          ${listingLine}
          <div class="inline">${actions.join("")}</div>
        </article>
      `;
    })
    .join("");
}

function renderTransactions() {
  if (!state.user) {
    refs.transactionsGrid.innerHTML = "";
    return;
  }
  if (!state.transactions.length) {
    refs.transactionsGrid.innerHTML = "<p>Nenhuma movimentação ainda.</p>";
    return;
  }
  refs.transactionsGrid.innerHTML = state.transactions
    .map(
      (txn) => `
      <article class="ledger-row">
        <div>
          <strong>${escapeHtml(txn.movieTitle)}</strong>
          <small>${escapeHtml(transactionLabel(txn.type))}</small>
        </div>
        <div class="ledger-meta">
          <span>${formatPriceFromCents(txn.priceCents)}</span>
          <small>${new Date(txn.createdAt).toLocaleString("pt-BR")}</small>
        </div>
      </article>
    `
    )
    .join("");
}

function renderPendingBanner() {
  const pending = (state.orders || []).filter((order) => order.status === "pending");
  const opening = (state.shares || []).filter((share) => share.tokenState?.code === "opening_player");
  if (!pending.length && !opening.length) {
    refs.pendingBanner.hidden = true;
    refs.pendingBanner.innerHTML = "";
    return;
  }
  refs.pendingBanner.hidden = false;
  const parts = [];
  if (opening.length) {
    const first = opening[0];
    parts.push(
      `<strong>Sessão Bunny em andamento.</strong> O token de ${escapeHtml(first.movie?.title || "um filme")} está em uso. Se o player não abrir, ele volta a ficar ativo. <button type="button" class="ghost" data-action="resume-playback" data-share-id="${first.id}" data-movie-title="${escapeHtml(first.movie?.title || "Filme")}">Continuar no player</button>`
    );
  }
  if (pending.length) {
    parts.push(
      `<strong>Checkout em andamento.</strong> ${pending.length === 1 ? "Uma cota está reservada" : `${pending.length} cotas estão reservadas`} até o pagamento ser confirmado.`
    );
  }
  refs.pendingBanner.innerHTML = parts.join("");
}

function renderBunnyStatus() {
  if (!refs.bunnyStatusCopy) return;
  const bunny = state.bunny || {};
  const libraryInput = refs.movieForm?.bunnyLibraryId;
  if (libraryInput && bunny.defaultLibraryId && !libraryInput.value) {
    libraryInput.value = bunny.defaultLibraryId;
  }
  if (refs.bunnyCreateBtn) refs.bunnyCreateBtn.hidden = !bunny.canCreate;
  if (bunny.canCreate) {
    refs.bunnyStatusCopy.textContent =
      "Bunny Stream está ligado neste servidor. Crie o vídeo aqui ou cole um ID já existente. O token do espectador só é gasto quando essa sessão abre.";
  } else if (bunny.hasLibrary) {
    refs.bunnyStatusCopy.textContent =
      "A biblioteca Bunny já está definida. Cole o ID do vídeo para o player funcionar.";
  } else {
    refs.bunnyStatusCopy.textContent =
      "Informe biblioteca e ID do vídeo da Bunny. Sem isso, a cota até vende — mas o player não abre.";
  }
  if (refs.bunnyHint) {
    refs.bunnyHint.textContent = bunny.signedEmbeds
      ? "O embed vai assinado. O token só é marcado como usado se a sessão Bunny abrir."
      : "O player usa o embed da Bunny. O token só é marcado como usado se a sessão abrir.";
  }
}

function renderAll() {
  renderSession();
  renderGenreFilter();
  renderMovies();
  renderListings();
  renderShares();
  renderTransactions();
  renderPendingBanner();
}

async function refreshData() {
  const [moviesResp, listingsResp, paymentsResp, bunnyResp] = await Promise.all([
    api("/api/movies"),
    api("/api/listings"),
    api("/api/payments/config"),
    api("/api/bunny/status").catch(() => ({ bunny: null }))
  ]);
  state.movies = moviesResp.movies || [];
  state.listings = listingsResp.listings || [];
  state.payments = paymentsResp.payments || null;
  state.bunny = bunnyResp.bunny || null;
  renderBunnyStatus();

  if (state.user) {
    const [sharesResp, txResp, ordersResp] = await Promise.all([
      api("/api/me/shares"),
      api("/api/me/transactions"),
      api("/api/me/orders")
    ]);
    state.shares = sharesResp.shares || [];
    state.transactions = txResp.transactions || [];
    state.orders = ordersResp.orders || [];
  } else {
    state.shares = [];
    state.transactions = [];
    state.orders = [];
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
  if (!checkoutState || !orderId) return;
  if (!state.user) {
    state.pendingAction = { type: "checkout-return" };
    notify("Faça login para concluir o retorno do pagamento.", true);
    showView("account");
    return;
  }

  if (checkoutState === "cancel") {
    await api(`/api/payments/orders/${orderId}/cancel`, { method: "POST", body: {} });
    notify("Checkout cancelado. A cota voltou a ficar disponível.");
    return;
  }

  if (checkoutState === "success") {
    await api(`/api/payments/orders/${orderId}/confirm`, {
      method: "POST",
      body: { sessionId: sessionId || undefined }
    });
    notify("Pagamento confirmado. Sua cota já está no portfólio.");
    showView("portfolio");
  }
}

async function resumePendingAction() {
  const pending = state.pendingAction;
  state.pendingAction = null;
  if (!pending || !state.user) return;
  if (pending.type === "buy-primary") return buyPrimary(pending.movieId);
  if (pending.type === "buy-listing") return buyListing(pending.listingId);
  if (pending.type === "view") return showView(pending.view);
  if (pending.type === "checkout-return") return handleCheckoutReturn();
}

async function bootstrapSession() {
  refs.moviesGrid.innerHTML = skeletonCards();
  refs.marketGrid.innerHTML = skeletonCards(2);
  showView(currentHashView(), { updateHash: false });

  if (state.sessionToken) {
    try {
      const me = await api("/api/auth/me");
      setSession(state.sessionToken, me.user);
    } catch {
      setSession("", null);
    }
  } else {
    renderSession();
  }

  try {
    await handleCheckoutReturn();
  } catch (error) {
    notify(error.message, true);
  }
  await refreshData();
  clearCheckoutQueryParams();
  if (state.user && currentHashView() === "account") showView("catalog");
}

async function register(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form).entries());
  await withLoading(async () => {
    const response = await api("/api/auth/register", { method: "POST", body: payload });
    setSession(response.sessionToken, response.user);
    notify("Conta criada. Bem-vindo à Urbe.");
    form.reset();
    await refreshData();
    await resumePendingAction();
    if (state.view === "account") showView("catalog");
  });
}

async function login(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form).entries());
  await withLoading(async () => {
    const response = await api("/api/auth/login", { method: "POST", body: payload });
    setSession(response.sessionToken, response.user);
    notify(`Olá, ${response.user.name}.`);
    form.reset();
    await refreshData();
    await resumePendingAction();
    if (state.view === "account") showView("catalog");
  });
}

async function logout() {
  try {
    await api("/api/auth/logout", { method: "POST" });
  } catch {
    // Sessão pode já estar inválida.
  }
  setSession("", null);
  notify("Sessão encerrada.");
  await refreshData();
  showView("catalog");
}

async function createBunnyVideo() {
  const title = String(refs.movieForm?.title?.value || "").trim();
  if (!title) {
    notify("Preencha o título do filme antes de criar o vídeo na Bunny.", true);
    return;
  }
  await withLoading(async () => {
    const response = await api("/api/bunny/videos", {
      method: "POST",
      body: {
        title,
        libraryId: refs.movieForm?.bunnyLibraryId?.value || state.bunny?.defaultLibraryId
      }
    });
    const videoId = response.videoId || response.bunnyVideo?.guid;
    const libraryId = response.libraryId || state.bunny?.defaultLibraryId;
    if (!videoId) throw new Error("A Bunny não devolveu o ID do vídeo.");
    if (refs.movieForm?.bunnyVideoId) refs.movieForm.bunnyVideoId.value = videoId;
    if (libraryId && refs.movieForm?.bunnyLibraryId) refs.movieForm.bunnyLibraryId.value = libraryId;
    const ready = response.readyToPlay ? "já pode tocar" : "criado — envie o arquivo no painel da Bunny para o player ficar pronto";
    notify(`Vídeo ${videoId} ${ready}.`);
    if (refs.bunnyHint) {
      refs.bunnyHint.textContent = `ID preenchido. ${ready.charAt(0).toUpperCase()}${ready.slice(1)}.`;
    }
  });
}

async function createMovie(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const formData = new FormData(form);
  const priceCents = parseReaisToCents(formData.get("priceReais"));
  if (!Number.isFinite(priceCents)) {
    notify("Informe um preço válido em reais, por exemplo 25,00.", true);
    return;
  }

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
    priceCents,
    totalShares: Number(formData.get("totalShares")),
    bunnyVideoId: formData.get("bunnyVideoId"),
    bunnyLibraryId: formData.get("bunnyLibraryId") || undefined
  };

  await withLoading(async () => {
    await api("/api/movies", { method: "POST", body: payload });
    notify("Filme publicado. As cotas já estão no catálogo com player Bunny.");
    form.reset();
    renderBunnyStatus();
    await refreshData();
    showView("catalog");
  });
}

async function handleCheckoutResponse(response, movieTitle) {
  if (response.checkout?.provider === "openpix") {
    mostrarModalPix({ order: response.order, checkout: response.checkout }, movieTitle);
    return "pix";
  }
  if (response.purchase) {
    notify("Pagamento aprovado. Cota liberada no seu portfólio.");
    await refreshData();
    showView("portfolio");
    return "done";
  }
  if (response.checkout?.checkoutUrl) {
    notify("Redirecionando para o checkout seguro...");
    window.location.href = response.checkout.checkoutUrl;
    return "redirect";
  }
  if (response.order?.id) {
    await api(`/api/payments/orders/${response.order.id}/confirm`, {
      method: "POST",
      body: { sessionId: response.checkout?.sessionId || undefined }
    });
    notify("Pagamento confirmado. Cota liberada.");
    await refreshData();
    showView("portfolio");
    return "done";
  }
  await refreshData();
  return "done";
}

function requestPrimaryPurchase(movieId) {
  if (!state.user) {
    state.pendingAction = { type: "buy-primary", movieId };
    requireAuth("buy");
    return;
  }
  return buyPrimary(movieId);
}

function requestListingPurchase(listingId) {
  if (!state.user) {
    state.pendingAction = { type: "buy-listing", listingId };
    requireAuth("buy");
    return;
  }
  return buyListing(listingId);
}

async function buyPrimary(movieId) {
  const movie = state.movies.find((item) => item.id === movieId);
  await withLoading(async () => {
    const response = await api(`/api/payments/primary/${movieId}/checkout`, { method: "POST", body: {} });
    await handleCheckoutResponse(response, movie?.title || "Cota");
  });
}

async function buyListing(listingId) {
  const listing = state.listings.find((item) => item.id === listingId);
  await withLoading(async () => {
    const response = await api(`/api/payments/listings/${listingId}/checkout`, { method: "POST", body: {} });
    await handleCheckoutResponse(response, listing?.movie?.title || "Cota");
  });
}

function openListingDialog(shareId) {
  const share = state.shares.find((item) => item.id === shareId);
  state.listingShareId = shareId;
  refs.listingMovieTitle.textContent = share?.movie?.title
    ? `Revenda de ${share.movie.title}`
    : "Defina o preço da revenda";
  refs.listingPrice.value = centsToReaisInput(share?.lastPriceCents || share?.movie?.priceCents || 2500);
  refs.listingDialog.showModal();
  refs.listingPrice.focus();
}

async function submitListing(event) {
  event.preventDefault();
  const priceCents = parseReaisToCents(refs.listingPrice.value);
  if (!Number.isFinite(priceCents)) {
    notify("Informe um preço válido em reais.", true);
    return;
  }
  await withLoading(async () => {
    await api(`/api/shares/${state.listingShareId}/listings`, {
      method: "POST",
      body: { priceCents }
    });
    notify("Cota anunciada no mercado secundário.");
    refs.listingDialog.close();
    await refreshData();
    showView("market");
  });
}

async function cancelListing(listingId) {
  await withLoading(async () => {
    await api(`/api/listings/${listingId}/cancel`, { method: "POST", body: {} });
    notify("Anúncio removido. A cota voltou para você.");
    await refreshData();
  });
}

function confirmWatch(token, movieTitle, shareId) {
  state.confirmAction = { type: "watch", token, movieTitle, shareId };
  refs.confirmTitle.textContent = "Abrir o player Bunny?";
  refs.confirmCopy.textContent = `${movieTitle} usa uma visualização única. O token só é gasto se a sessão Bunny abrir. Se o player falhar, a cota continua pronta para assistir.`;
  refs.confirmAccept.textContent = "Abrir player";
  refs.confirmDialog.showModal();
}

async function submitConfirm(event) {
  event.preventDefault();
  refs.confirmDialog.close();
  const action = state.confirmAction;
  state.confirmAction = null;
  if (action?.type === "watch") await consumeToken(action.token, action.movieTitle, action.shareId);
}

async function openPlayer(playbackUrl, movieTitle, statusText, shareId) {
  if (!playbackUrl) throw new Error("Não foi possível gerar o link de reprodução.");
  refs.playerTitle.textContent = `${movieTitle} · sessão Bunny`;
  if (refs.playerStatus) refs.playerStatus.textContent = statusText;
  playbackShareId = shareId || "";
  refs.playerFrame.src = playbackUrl;
  refs.playerDialog.showModal();
  if (playbackShareId) startPlaybackPoll(playbackShareId);
}

function stopPlaybackPoll() {
  if (playbackPollInterval) clearInterval(playbackPollInterval);
  playbackPollInterval = null;
}

function startPlaybackPoll(shareId) {
  playbackShareId = shareId;
  stopPlaybackPoll();
  playbackPollInterval = setInterval(() => {
    syncPlaybackState().catch(() => {});
  }, 2000);
}

async function syncPlaybackState() {
  if (!state.user) return;
  const sharesResp = await api("/api/me/shares");
  state.shares = sharesResp.shares || [];
  const share = playbackShareId ? state.shares.find((item) => item.id === playbackShareId) : null;
  if (share && refs.playerStatus) {
    const story = tokenStory(share);
    if (story.code === "used" || share.tokenState?.code === "used") {
      refs.playerStatus.textContent = "Sessão Bunny aberta. Token usado — esta visualização não se repete.";
      stopPlaybackPoll();
    } else if (share.tokenState?.code === "ready") {
      refs.playerStatus.textContent = "O player não confirmou a sessão. Seu token voltou a ficar ativo.";
      stopPlaybackPoll();
    } else if (share.tokenState?.code === "opening_player") {
      const left = story.playbackRemainingSeconds ? ` Expira em ${formatCountdown(story.playbackRemainingSeconds)}.` : "";
      refs.playerStatus.textContent = `Conectando ao Bunny Stream. Token em uso.${left}`;
    }
  }
  renderShares();
  renderPendingBanner();
}

function applyWatchMessage(data) {
  if (!refs.playerStatus) return;
  if (data.tokenSpent) {
    refs.playerStatus.textContent = "Sessão Bunny aberta. Token usado — esta visualização não se repete.";
    stopPlaybackPoll();
  } else if (data.code === "PLAYBACK_FORBIDDEN") {
    refs.playerStatus.textContent = "Abra pelo mesmo navegador. O token continua em sessão — use Continuar no player.";
  } else {
    refs.playerStatus.textContent = data.message
      ? `${data.message}`
      : "Player não abriu. Seu token não foi gasto.";
  }
  refreshData().catch((error) => notify(error.message, true));
}

async function consumeToken(token, movieTitle, shareId) {
  await withLoading(async () => {
    const response = await api("/api/access/consume", { method: "POST", body: { token } });
    const playbackUrl = response.playback.watchUrl || response.playback.watchPath || response.playback.embedUrl;
    await openPlayer(
      playbackUrl,
      movieTitle,
      "Conectando ao Bunny Stream. Se o player não abrir, seu token volta a ficar ativo.",
      response.share?.id || shareId
    );
    notify("Sessão Bunny pedida. O token só confirma o uso depois que o player abrir.");
    await refreshData();
  });
}

async function resumeWatch(shareId, movieTitle) {
  await withLoading(async () => {
    const response = await api("/api/access/resume", { method: "POST", body: { shareId } });
    const playbackUrl = response.playback.watchUrl || response.playback.watchPath;
    await openPlayer(playbackUrl, movieTitle, "Retomando a sessão Bunny em andamento.", response.share?.id || shareId);
    notify("Retomando o player. O estado do token atualiza quando a sessão abrir.");
    await refreshData();
  });
}

function mostrarModalPix(payload, movieTitle) {
  const order = payload?.order || payload || {};
  const checkout = payload?.checkout || payload || {};
  pixOrderId = order.id || payload?.orderId || payload?.id || "";
  pixSessionId = checkout.sessionId || payload?.sessionId || "";
  const qrCodeRaw = checkout.qrCodeBase64 || payload?.qrCodeBase64 || "";
  const qrCodeSrc = pixImageSrc(qrCodeRaw);

  refs.pixMovieTitle.textContent = movieTitle || "Cota de visualização";
  refs.pixQrCode.src = qrCodeSrc || "";
  refs.pixQrCode.hidden = !qrCodeSrc;
  refs.pixCopiaCola.value = checkout.pixCopiaECola || payload?.pixCopiaECola || "";

  if (!pixOrderId) {
    notify("Não foi possível preparar o checkout Pix.", true);
    return;
  }

  const expiresIn = Number(checkout.expiresIn || state.payments?.checkoutReservationMinutes * 60 || 15 * 60);
  startPixTimer(expiresIn);
  startPixPolling();
  refs.pixDialog.showModal();
}

function startPixTimer(totalSeconds) {
  let timeLeft = Math.max(1, Number(totalSeconds) || 15 * 60);
  const tick = () => {
    const min = Math.floor(timeLeft / 60);
    const sec = timeLeft % 60;
    refs.pixTimer.textContent = `${min}:${sec < 10 ? "0" : ""}${sec}`;
    if (timeLeft <= 0) {
      clearInterval(pixTimerInterval);
      refs.pixTimer.textContent = "Expirado";
      stopPixPolling();
    }
    timeLeft -= 1;
  };
  clearInterval(pixTimerInterval);
  tick();
  pixTimerInterval = setInterval(tick, 1000);
}

function startPixPolling() {
  stopPixPolling();
  pixPollInterval = setInterval(() => {
    verificarPagamentoPix({ silent: true });
  }, 3000);
}

function stopPixPolling() {
  if (pixPollInterval) clearInterval(pixPollInterval);
  pixPollInterval = null;
}

async function copiarPix() {
  const value = refs.pixCopiaCola.value;
  if (!value) {
    notify("Código Pix indisponível.", true);
    return;
  }
  try {
    if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(value);
    else {
      refs.pixCopiaCola.select();
      document.execCommand("copy");
    }
    notify("Código Pix copiado.");
  } catch {
    notify("Não foi possível copiar o código Pix.", true);
  }
}

function fecharPixModal() {
  if (refs.pixDialog.open) refs.pixDialog.close();
  clearInterval(pixTimerInterval);
  stopPixPolling();
  pixOrderId = "";
  pixSessionId = "";
}

async function verificarPagamentoPix({ silent = false } = {}) {
  if (!pixOrderId) return;
  try {
    const data = await api(`/api/payments/orders/${pixOrderId}/confirm`, {
      method: "POST",
      body: { sessionId: pixSessionId || undefined }
    });
    const isPaid = Boolean(data.purchase) || Boolean(data.alreadyPaid) || data.order?.status === "paid";
    if (isPaid) {
      notify("Pagamento confirmado. Token liberado.");
      fecharPixModal();
      await refreshData();
      showView("portfolio");
      return;
    }
    if (!silent) notify("Ainda não detectamos o pagamento. Tente de novo em alguns segundos.");
  } catch (error) {
    if (!silent) notify(error?.message || "Erro ao verificar pagamento", true);
  }
}

function updatePriceHint() {
  const cents = parseReaisToCents(refs.movieForm?.priceReais?.value);
  if (!refs.priceHint) return;
  if (!Number.isFinite(cents)) {
    refs.priceHint.textContent = "O comprador paga esse valor por uma visualização.";
    return;
  }
  refs.priceHint.textContent = `Cada cota sairá por ${formatPriceFromCents(cents)}.`;
}

function bindGlobalActions() {
  document.body.addEventListener("click", async (event) => {
    const target = event.target.closest("[data-action], [data-nav]");
    if (!(target instanceof HTMLElement)) return;

    if (target.dataset.nav) {
      event.preventDefault();
      const dest = target.dataset.nav;
      if (target.dataset.authRequired === "true" && !state.user) {
        state.pendingAction = { type: "view", view: dest };
        requireAuth(dest === "publish" ? "publish" : "portfolio");
        refs.accountCopy.textContent =
          dest === "publish" ? "Entre para publicar um filme e emitir cotas." : "Entre para ver suas cotas e tokens.";
        showView("account");
        return;
      }
      showView(dest);
      return;
    }

    const actionName = target.dataset.action;
    if (!actionName || !actionHandlers[actionName]) return;
    try {
      await actionHandlers[actionName](target);
    } catch (error) {
      notify(error.message, true);
    }
  });

  refs.playerDialog.addEventListener("close", () => {
    refs.playerFrame.src = "";
    stopPlaybackPoll();
    playbackShareId = "";
    if (refs.playerStatus) {
      refs.playerStatus.textContent = "Conectando ao Bunny Stream. O token só é usado se o player abrir.";
    }
    refreshData().catch((error) => notify(error.message, true));
  });
  refs.playerFrame.addEventListener("load", () => {
    if (!refs.playerFrame.src) return;
    syncPlaybackState().catch(() => {});
  });
  window.addEventListener("message", (event) => {
    if (event.origin !== window.location.origin) return;
    const data = event.data;
    if (!data || data.source !== "urbe-watch") return;
    applyWatchMessage(data);
  });
  refs.pixDialog.addEventListener("close", () => {
    clearInterval(pixTimerInterval);
    stopPixPolling();
  });
  document.querySelectorAll(".dialog-close").forEach((button) => {
    button.addEventListener("click", () => button.closest("dialog")?.close());
  });
}

function bindForms() {
  refs.registerForm.addEventListener("submit", (event) => register(event).catch((error) => notify(error.message, true)));
  refs.loginForm.addEventListener("submit", (event) => login(event).catch((error) => notify(error.message, true)));
  refs.logoutBtn.addEventListener("click", () => logout().catch((error) => notify(error.message, true)));
  refs.loginBtn.addEventListener("click", () => {
    refs.accountCopy.textContent = "Crie uma conta ou faça login para comprar, assistir e publicar.";
    showView("account");
  });
  refs.movieForm.addEventListener("submit", (event) => createMovie(event).catch((error) => notify(error.message, true)));
  refs.movieForm.querySelector('[name="priceReais"]').addEventListener("input", updatePriceHint);
  refs.bunnyCreateBtn?.addEventListener("click", () => createBunnyVideo().catch((error) => notify(error.message, true)));
  refs.listingForm.addEventListener("submit", (event) => submitListing(event).catch((error) => notify(error.message, true)));
  refs.confirmForm.addEventListener("submit", (event) => submitConfirm(event).catch((error) => notify(error.message, true)));
  refs.pixCopyBtn.addEventListener("click", () => copiarPix());
  refs.pixCheckBtn.addEventListener("click", () => verificarPagamentoPix({ silent: false }));
  refs.movieSearch.addEventListener("input", () => {
    state.search = refs.movieSearch.value;
    renderMovies();
  });
  refs.movieGenre.addEventListener("change", () => {
    state.genre = refs.movieGenre.value;
    renderMovies();
  });
  window.addEventListener("hashchange", () => showView(currentHashView(), { updateHash: false }));
}

bindGlobalActions();
bindForms();
bootstrapSession().catch((error) => {
  console.error(error);
  notify(error?.message || "Falha ao inicializar a aplicação.", true);
});
