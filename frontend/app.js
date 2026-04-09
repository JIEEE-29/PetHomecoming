const API_BASE = (window.APP_CONFIG && window.APP_CONFIG.API_BASE) || "http://127.0.0.1:8000";

const state = {
  token: localStorage.getItem("pet_homecoming_token") || "",
  currentUser: null,
  rawImage: "",
  processedImage: "",
  visionReport: null,
  cameraStream: null,
};

const page = document.body.dataset.page;

function $(selector) {
  return document.querySelector(selector);
}

function notify(message) {
  window.alert(message);
}

async function apiFetch(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "请求失败");
  return data;
}

function saveToken(token) {
  state.token = token;
  if (token) localStorage.setItem("pet_homecoming_token", token);
  else localStorage.removeItem("pet_homecoming_token");
}

function renderGlobalUser() {
  const globalUser = $("#globalUser");
  if (!globalUser) return;
  if (state.currentUser) {
    globalUser.textContent = state.currentUser.full_name;
    globalUser.href = "./auth.html";
  } else {
    globalUser.textContent = "登录";
    globalUser.href = "./login.html";
  }
}

async function restoreSession() {
  if (!state.token) {
    state.currentUser = null;
    renderGlobalUser();
    return;
  }
  try {
    const data = await apiFetch("/api/me");
    state.currentUser = data.user;
  } catch {
    saveToken("");
    state.currentUser = null;
  }
  renderGlobalUser();
}

function normalizeCategoryLabel(value) {
  const text = String(value || "").trim();
  if (!text) return "";

  const directMap = {
    dog: "\u72ac\u7c7b",
    cat: "\u732b\u7c7b",
    bird: "\u9e1f\u7c7b",
    other: "\u5176\u4ed6",
    small_pet: "\u5c0f\u578b\u5ba0\u7269",
    pending_manual: "\u5f85\u4eba\u5de5\u786e\u8ba4",
    "\u72ac\u7c7b": "\u72ac\u7c7b",
    "\u732b\u7c7b": "\u732b\u7c7b",
    "\u9e1f\u7c7b": "\u9e1f\u7c7b",
    "\u5176\u4ed6": "\u5176\u4ed6",
    "\u5c0f\u578b\u5ba0\u7269": "\u5c0f\u578b\u5ba0\u7269",
    "\u5f85\u4eba\u5de5\u786e\u8ba4": "\u5f85\u4eba\u5de5\u786e\u8ba4",
    "\u6966\u71ba\u88ab": "\u9e1f\u7c7b",
    "\u941a\ue0a4\u88ab": "\u732b\u7c7b",
    "\u9418\ue102\u88ab": "\u72ac\u7c7b",
  };
  if (directMap[text]) return directMap[text];

  const fallbackPatterns = [
    ["dog", "\u72ac\u7c7b"],
    ["cat", "\u732b\u7c7b"],
    ["bird", "\u9e1f\u7c7b"],
    ["\u9418", "\u72ac\u7c7b"],
    ["\u941a", "\u732b\u7c7b"],
    ["\u6966", "\u9e1f\u7c7b"],
    ["\u93c9", "\u5176\u4ed6"],
    ["\u704f\u5fd5\u7037", "\u5c0f\u578b\u5ba0\u7269"],
    ["\u5be0\u4eba\u5de5", "\u5f85\u4eba\u5de5\u786e\u8ba4"],
  ];
  const lower = text.toLowerCase();
  if (text.includes("\u6966") || text.includes("\u71ba\u88ab")) return "\u9e1f\u7c7b";
  if (text.includes("\u941a") || text.includes("\ue0a4\u88ab")) return "\u732b\u7c7b";
  if (text.includes("\u9418") || text.includes("\ue102\u88ab")) return "\u72ac\u7c7b";
  for (const [needle, label] of fallbackPatterns) {
    if (text.includes(needle) || lower.includes(needle.toLowerCase())) return label;
  }
  return text;
}

function formatRecognitionCard(recognition) {
  if (!recognition) return "尚未识别";
  const yolo = recognition.yolo || {};
  const sourceLabelMap = {
    yolo: "YOLO",
    rule: "规则",
    manual: "人工选择",
  };
  const categoryLabel = recognition.recognized_category_label || recognition.recognized_category || "待确认";
  const stateLabel = recognition.recognized_state_label || recognition.recognized_state || "待确认";
  const notes = (recognition.notes || []).length ? recognition.notes.join("；") : "无";
  const recommendations = (recognition.recommendations || []).length ? recognition.recommendations.join("；") : "无";
  const detections = (yolo.detections || []).length
    ? yolo.detections
        .slice(0, 4)
        .map((item) => `${item.label || item.model_label} ${Number(item.confidence).toFixed(2)}`)
        .join("；")
    : "无";
  return `
    自动分类：${categoryLabel}（${recognition.category_confidence}）<br>
    分类来源：${sourceLabelMap[recognition.category_source] || recognition.category_source || "未知"}<br>
    自动状态：${stateLabel}（${recognition.state_confidence}）<br>
    YOLO 状态：${yolo.status || "skipped"}${yolo.model ? ` / ${yolo.model}` : ""}<br>
    检测结果：${detections}<br>
    识别说明：${notes}<br>
    建议：${recommendations}
  `;
}

function formatRecognition(recognition) {
  if (!recognition) return "尚未识别";
  return `
    自动分类：${recognition.recognized_category}（${recognition.category_confidence}）<br>
    自动状态：${recognition.recognized_state}（${recognition.state_confidence}）<br>
    识别说明：${(recognition.notes || []).join("；") || "无"}<br>
    建议：${(recognition.recommendations || []).join("；")}
  `;
}

function renderList(container, items, formatter) {
  if (!container) return;
  if (!items.length) {
    container.innerHTML = `<div class="list-item">暂无记录</div>`;
    return;
  }
  container.innerHTML = "";
  items.forEach((item) => {
    const node = document.createElement("div");
    node.className = "list-item";
    node.innerHTML = formatter(item);
    container.appendChild(node);
  });
}

async function loadPetDetails(petId, commentContainer, contactContainer) {
  const data = await apiFetch(`/api/pets/${petId}`);
  renderList(commentContainer, data.comments, (item) => `<strong>${item.full_name}</strong>${item.created_at}<br>${item.content}`);
  renderList(contactContainer, data.contacts, (item) => `<strong>${item.full_name}</strong>${item.contact_type} · ${item.phone}<br>${item.message}`);
}

async function loadHomeStats() {
  const petCount = $("#petCount");
  if (petCount) {
    const petData = await apiFetch("/api/pets");
    petCount.textContent = String(petData.pets.length);
  }
  const pendingCount = $("#pendingCount");
  if (!pendingCount) return;
  if (!state.currentUser || state.currentUser.role !== "admin") {
    pendingCount.textContent = "0";
    return;
  }
  const pendingData = await apiFetch("/api/users/pending");
  pendingCount.textContent = String(pendingData.users.length);
}

function bindRegisterForm(registerForm, successRedirect) {
  registerForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(registerForm).entries());
    try {
      const data = await apiFetch("/api/register", { method: "POST", body: JSON.stringify(payload) });
      registerForm.reset();
      notify(data.message);
      if (successRedirect) window.location.href = successRedirect;
    } catch (error) {
      notify(error.message);
    }
  });
}

function bindLoginForm(loginForm) {
  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(loginForm).entries());
    try {
      const data = await apiFetch("/api/login", { method: "POST", body: JSON.stringify(payload) });
      saveToken(data.token);
      state.currentUser = data.user;
      renderGlobalUser();
      notify("登录成功。");
      window.location.href = "./auth.html";
    } catch (error) {
      notify(error.message);
    }
  });
}

function initAuthPage() {
  const authStatus = $("#authStatus");
  const authGuard = $("#authGuard");
  const currentUserCard = $("#currentUserCard");
  const authActions = $("#authActions");
  const logoutBtn = $("#logoutBtn");

  authStatus.textContent = state.currentUser ? `${state.currentUser.full_name} · ${state.currentUser.role}` : "未登录";

  if (!state.currentUser) {
    authGuard.classList.remove("hidden");
    authGuard.innerHTML = `当前未登录，请先 <a class="inline-link" href="./login.html">登录</a> 后查看账户信息。`;
    return;
  }

  currentUserCard.classList.remove("hidden");
  authActions.classList.remove("hidden");
  currentUserCard.innerHTML = `
    <strong>${state.currentUser.full_name}</strong><br>
    用户名：${state.currentUser.username}<br>
    电话：${state.currentUser.phone}<br>
    邮箱：${state.currentUser.email || "未填写"}<br>
    地址：${state.currentUser.address || "未填写"}<br>
    证件号：${state.currentUser.id_card || "未填写"}<br>
    审核状态：${state.currentUser.review_status}<br>
    角色：${state.currentUser.role}
  `;

  logoutBtn.addEventListener("click", async () => {
    try {
      await apiFetch("/api/logout", { method: "POST", body: JSON.stringify({}) });
    } catch {
    }
    saveToken("");
    state.currentUser = null;
    renderGlobalUser();
    notify("已退出登录。");
    window.location.href = "./index.html";
  });
}

function initLoginPage() {
  bindLoginForm($("#loginForm"));
}

function initRegisterPage() {
  bindRegisterForm($("#registerForm"), "./login.html");
}

function analyzeImageData(imageData) {
  const { data } = imageData;
  const pixels = data.length / 4;
  let red = 0;
  let green = 0;
  let blue = 0;
  let brightness = 0;
  let variance = 0;

  for (let index = 0; index < data.length; index += 4) {
    const r = data[index];
    const g = data[index + 1];
    const b = data[index + 2];
    const light = 0.299 * r + 0.587 * g + 0.114 * b;
    red += r;
    green += g;
    blue += b;
    brightness += light;
  }

  const averageBrightness = brightness / pixels;
  for (let index = 0; index < data.length; index += 4) {
    const light = 0.299 * data[index] + 0.587 * data[index + 1] + 0.114 * data[index + 2];
    variance += Math.pow(light - averageBrightness, 2);
  }

  const averageRed = red / pixels;
  const averageGreen = green / pixels;
  const averageBlue = blue / pixels;
  const contrast = Math.sqrt(variance / pixels);
  let dominant = "灰白";

  if (averageRed > averageGreen + 18 && averageRed > averageBlue + 18) dominant = "偏暖/棕橙";
  if (averageGreen > averageRed + 18 && averageGreen > averageBlue + 18) dominant = "偏绿";
  if (averageBlue > averageRed + 18 && averageBlue > averageGreen + 18) dominant = "偏蓝";

  return {
    brightness: Number(averageBrightness.toFixed(2)),
    contrast: Number(contrast.toFixed(2)),
    average_rgb: [Math.round(averageRed), Math.round(averageGreen), Math.round(averageBlue)],
    dominant_color: dominant,
    clarity_level: contrast > 55 ? "较清晰" : contrast > 28 ? "一般" : "偏模糊",
  };
}

async function loadImageToCanvas(source, canvas, rawPreview, processedPreview, visionMetrics) {
  const image = new Image();
  image.src = source;
  await image.decode();
  const width = Math.min(960, image.width);
  const height = Math.round((image.height / image.width) * width);
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  context.filter = "none";
  context.drawImage(image, 0, 0, width, height);
  state.rawImage = canvas.toDataURL("image/jpeg", 0.9);
  context.filter = "contrast(1.08) saturate(1.08)";
  context.drawImage(image, 0, 0, width, height);
  state.processedImage = canvas.toDataURL("image/jpeg", 0.86);
  state.visionReport = analyzeImageData(context.getImageData(0, 0, width, height));
  rawPreview.src = state.rawImage;
  processedPreview.src = state.processedImage;
  visionMetrics.textContent = JSON.stringify(state.visionReport, null, 2);
}

function selectDetectedCategory(categorySelect, categoryKey) {
  const optionIndexByKey = {
    dog: 1,
    cat: 2,
    bird: 3,
    other: 5,
  };
  const optionIndex = optionIndexByKey[categoryKey];
  if (typeof optionIndex !== "number" || !categorySelect.options[optionIndex]) return;
  categorySelect.selectedIndex = optionIndex;
}

async function analyzeUploadedImage(recognitionCard, processedPreview, categorySelect) {
  if (!state.rawImage) return;
  recognitionCard.classList.remove("hidden");
  recognitionCard.innerHTML = "YOLO 识别中...";
  categorySelect.selectedIndex = 0;

  try {
    const data = await apiFetch("/api/pets/analyze", {
      method: "POST",
      body: JSON.stringify({ image_data_url: state.rawImage }),
    });
    if (data.category_key) {
      selectDetectedCategory(categorySelect, data.category_key);
    }
    if (data.processed_image_path) {
      processedPreview.src = `${API_BASE}${data.processed_image_path}`;
    }
    recognitionCard.innerHTML = formatRecognitionCard(data.recognition);
  } catch (error) {
    recognitionCard.innerHTML = `YOLO 识别失败：${error.message}`;
  }
}

async function handlePublishFile(file, captureCanvas, rawPreview, processedPreview, visionMetrics, recognitionCard, manualCategorySelect) {
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    notify("请上传图片文件。");
    return;
  }
  const reader = new FileReader();
  reader.onload = async () => {
    await loadImageToCanvas(reader.result, captureCanvas, rawPreview, processedPreview, visionMetrics);
    await analyzeUploadedImage(recognitionCard, processedPreview, manualCategorySelect);
  };
  reader.readAsDataURL(file);
}

function initPublishPage() {
  const imageFileInput = $("#imageFileInput");
  const uploadButton = $("#uploadButton");
  const captureCanvas = $("#captureCanvas");
  const rawPreview = $("#rawPreview");
  const processedPreview = $("#processedPreview");
  const visionMetrics = $("#visionMetrics");
  const petForm = $("#petForm");
  const recognitionCard = $("#recognitionCard");
  const manualCategorySelect = $("#manualCategorySelect");
  const previewGrid = $(".image-preview-grid");
  const metricsCard = $(".preview-card.metrics");

  if (previewGrid && recognitionCard && !previewGrid.contains(recognitionCard)) {
    previewGrid.appendChild(recognitionCard);
  }
  if (metricsCard) {
    metricsCard.remove();
  }

  if (uploadButton) {
    uploadButton.addEventListener("click", () => {
      imageFileInput.value = "";
      imageFileInput.click();
    });
  }

  imageFileInput.addEventListener("change", async (event) => {
    const file = event.target.files[0];
    await handlePublishFile(file, captureCanvas, rawPreview, processedPreview, visionMetrics, recognitionCard, manualCategorySelect);
  });

  petForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.rawImage) {
      notify("请先上传宠物图片。");
      return;
    }
    if (!state.token) {
      notify("请先登录后创建宠物档案。");
      window.location.href = "./login.html";
      return;
    }
    const payload = Object.fromEntries(new FormData(petForm).entries());
    payload.image_data_url = state.rawImage;
    payload.processed_image_data_url = state.processedImage;
    payload.vision_report = state.visionReport;
    try {
      const data = await apiFetch("/api/pets", { method: "POST", body: JSON.stringify(payload) });
      petForm.reset();
      recognitionCard.classList.remove("hidden");
      recognitionCard.innerHTML = formatRecognitionCard(data.recognition);
      if (data.processed_image_path) {
        processedPreview.src = `${API_BASE}${data.processed_image_path}`;
      }
      notify(data.message);
    } catch (error) {
      notify(error.message);
    }
  });
}

async function renderPetList(pets) {
  const petList = $("#petList");
  const petCardTemplate = $("#petCardTemplate");
  if (!pets.length) {
    petList.className = "pet-list empty";
    petList.textContent = "暂无宠物档案";
    return;
  }

  petList.className = "pet-list";
  petList.innerHTML = "";
  for (const pet of pets) {
    const fragment = petCardTemplate.content.cloneNode(true);
    const article = fragment.querySelector(".pet-card");
    const detailLink = fragment.querySelector(".pet-detail-link");
    const detailUrl = `./pet-detail.html?id=${pet.id}`;
    fragment.querySelector(".pet-image").src = pet.processed_image_path
      ? `${API_BASE}${pet.processed_image_path}`
      : pet.image_path
        ? `${API_BASE}${pet.image_path}`
        : "";
    fragment.querySelector(".pet-name").textContent = pet.name;
    fragment.querySelector(".pet-subtitle").textContent = `${pet.breed || "未填写品种"} · ${pet.found_location || "地点待补充"} · ${pet.created_at}`;
    fragment.querySelector(".pet-description").textContent = pet.description || "暂无描述";
    fragment.querySelector(".pet-state").textContent = pet.recognized_state_label || pet.recognized_state || pet.status;
    fragment.querySelector(".category-pill").dataset.labelOverride = normalizeCategoryLabel(
      pet.recognized_category_label || pet.recognized_category || pet.manual_category || ""
    );
    fragment.querySelector(".category-pill").textContent = normalizeCategoryLabel(
      pet.recognized_category || pet.manual_category || ""
    ) || "未分类";
    fragment.querySelector(".creator-pill").textContent = `发布人：${pet.creator_name}`;
    fragment.querySelector(".comment-pill").textContent = `评论 ${pet.comment_count || 0}`;
    if (fragment.querySelector(".category-pill").dataset.labelOverride) {
      fragment.querySelector(".category-pill").textContent = fragment.querySelector(".category-pill").dataset.labelOverride;
    }
    if (detailLink) {
      detailLink.href = detailUrl;
    }
    if (article) {
      article.tabIndex = 0;
      article.role = "link";
      article.addEventListener("click", (event) => {
        if (event.target.closest("a, button, input, select, textarea")) return;
        window.location.href = detailUrl;
      });
      article.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          window.location.href = detailUrl;
        }
      });
    }

    petList.appendChild(fragment);
  }
}

async function initPetsPage(skipBind = false) {
  const filterForm = $("#filterForm");
  const query = new URLSearchParams();
  for (const [key, value] of new FormData(filterForm).entries()) {
    if (value) query.set(key, value);
  }
  const data = await apiFetch(`/api/pets?${query.toString()}`);
  await renderPetList(data.pets);

  if (!skipBind && !filterForm.dataset.bound) {
    filterForm.dataset.bound = "1";
    filterForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      await initPetsPage(true);
    });
  }
}

function getPetIdFromQuery() {
  const value = new URLSearchParams(window.location.search).get("id") || "";
  return /^\d+$/.test(value) ? value : "";
}

async function initPetDetailPage() {
  const guard = $("#petDetailGuard");
  const card = $("#petDetailCard");
  const commentList = $("#detailCommentList");
  const contactList = $("#detailContactList");
  const commentForm = $("#detailCommentForm");
  const contactForm = $("#detailContactForm");
  const petId = getPetIdFromQuery();

  if (!petId) {
    guard.classList.remove("hidden");
    guard.textContent = "帖子不存在或链接无效。";
    return;
  }

  try {
    const data = await apiFetch(`/api/pets/${petId}`);
    const pet = data.pet;

    $("#petDetailImage").src = pet.processed_image_path
      ? `${API_BASE}${pet.processed_image_path}`
      : pet.image_path
        ? `${API_BASE}${pet.image_path}`
        : "";
    $("#petDetailName").textContent = pet.name;
    $("#petDetailSubtitle").textContent = `${pet.breed || "未填写品种"} · ${pet.found_location || "地点待补充"} · ${pet.created_at}`;
    $("#petDetailDescription").textContent = pet.description || "暂无描述";
    $("#petDetailState").textContent = pet.recognized_state_label || pet.recognized_state || pet.status;
    $("#petDetailCategory").textContent = normalizeCategoryLabel(pet.recognized_category_label || pet.recognized_category || pet.manual_category) || "未分类";
    $("#petDetailCreator").textContent = `发布人：${pet.creator_name}`;
    $("#petDetailComments").textContent = `评论 ${data.comments.length}`;

    renderList(commentList, data.comments, (item) => `<strong>${item.full_name}</strong> ${item.created_at}<br>${item.content}`);
    renderList(contactList, data.contacts, (item) => `<strong>${item.full_name}</strong> ${item.contact_type} · ${item.phone}<br>${item.message}`);

    if (!commentForm.dataset.bound) {
      commentForm.dataset.bound = "1";
      commentForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!state.token) {
          notify("请先登录后评论。");
          window.location.href = "./login.html";
          return;
        }
        const payload = Object.fromEntries(new FormData(commentForm).entries());
        try {
          await apiFetch(`/api/pets/${petId}/comments`, { method: "POST", body: JSON.stringify(payload) });
          commentForm.reset();
          await initPetDetailPage();
        } catch (error) {
          notify(error.message);
        }
      });
    }

    if (!contactForm.dataset.bound) {
      contactForm.dataset.bound = "1";
      contactForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!state.token) {
          notify("请先登录后提交联系申请。");
          window.location.href = "./login.html";
          return;
        }
        const payload = Object.fromEntries(new FormData(contactForm).entries());
        try {
          await apiFetch(`/api/pets/${petId}/contacts`, { method: "POST", body: JSON.stringify(payload) });
          contactForm.reset();
          await initPetDetailPage();
        } catch (error) {
          notify(error.message);
        }
      });
    }

    guard.classList.add("hidden");
    card.classList.remove("hidden");
  } catch (error) {
    card.classList.add("hidden");
    guard.classList.remove("hidden");
    guard.textContent = error.message || "帖子加载失败。";
  }
}

async function initAdminPage() {
  const adminGuard = $("#adminGuard");
  const pendingUsers = $("#pendingUsers");
  if (!state.currentUser || state.currentUser.role !== "admin") {
    adminGuard.classList.remove("hidden");
    adminGuard.textContent = "当前页面仅管理员可操作，请使用管理员账号登录。";
    pendingUsers.className = "stack-list empty";
    pendingUsers.textContent = "无可显示内容";
    return;
  }

  const loadPendingUsers = async () => {
    const data = await apiFetch("/api/users/pending");
    if (!data.users.length) {
      pendingUsers.className = "stack-list empty";
      pendingUsers.textContent = "暂无待审核人员";
      return;
    }
    pendingUsers.className = "stack-list";
    pendingUsers.innerHTML = "";
    data.users.forEach((user) => {
      const item = document.createElement("div");
      item.className = "list-item";
      item.innerHTML = `
        <strong>${user.full_name}</strong>
        用户名：${user.username}<br>
        电话：${user.phone}<br>
        邮箱：${user.email || "未填写"}<br>
        地址：${user.address || "未填写"}<br>
        证件号：${user.id_card || "未填写"}<br>
        <textarea data-note="${user.id}" placeholder="审核备注"></textarea>
        <div class="pill-row" style="margin-top:8px;">
          <button data-user-id="${user.id}" data-action="approved">审核通过</button>
          <button data-user-id="${user.id}" data-action="rejected" class="secondary">驳回</button>
        </div>
      `;
      pendingUsers.appendChild(item);
    });
  };

  await loadPendingUsers();

  if (!pendingUsers.dataset.bound) {
    pendingUsers.dataset.bound = "1";
    pendingUsers.addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-user-id]");
      if (!button) return;
      const payload = {
        status: button.dataset.action,
        review_note: pendingUsers.querySelector(`textarea[data-note="${button.dataset.userId}"]`)?.value || "",
      };
      try {
        await apiFetch(`/api/users/${button.dataset.userId}/review`, { method: "POST", body: JSON.stringify(payload) });
        await loadPendingUsers();
        notify("审核完成。");
      } catch (error) {
        notify(error.message);
      }
    });
  }
}

window.addEventListener("load", async () => {
  await restoreSession();
  if (page === "home") {
    await loadHomeStats();
    await initPetsPage();
  }
  if (page === "auth") initAuthPage();
  if (page === "login") initLoginPage();
  if (page === "register") initRegisterPage();
  if (page === "publish") initPublishPage();
  if (page === "pets") await initPetsPage();
  if (page === "pet-detail") await initPetDetailPage();
  if (page === "admin") await initAdminPage();
});
