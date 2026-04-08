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

async function apiFetch(url, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(url, { ...options, headers });
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
  globalUser.textContent = state.currentUser
    ? `${state.currentUser.full_name} · ${state.currentUser.role}`
    : "未登录";
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
  renderList(commentContainer, data.comments, (x) => `<strong>${x.full_name}</strong>${x.created_at}<br>${x.content}`);
  renderList(contactContainer, data.contacts, (x) => `<strong>${x.full_name}</strong>${x.contact_type} · ${x.phone}<br>${x.message}`);
}

async function loadHomeStats() {
  const petCount = $("#petCount");
  if (petCount) {
    const data = await apiFetch("/api/pets");
    petCount.textContent = String(data.pets.length);
  }
  const pendingCount = $("#pendingCount");
  if (!pendingCount) return;
  if (!state.currentUser || state.currentUser.role !== "admin") {
    pendingCount.textContent = "0";
    return;
  }
  const data = await apiFetch("/api/users/pending");
  pendingCount.textContent = String(data.users.length);
}

function initAuthPage() {
  const registerForm = $("#registerForm");
  const loginForm = $("#loginForm");
  const logoutBtn = $("#logoutBtn");
  const authStatus = $("#authStatus");
  const currentUserCard = $("#currentUserCard");

  authStatus.textContent = state.currentUser ? `${state.currentUser.full_name} · ${state.currentUser.role}` : "未登录";
  if (state.currentUser) {
    currentUserCard.classList.remove("hidden");
    currentUserCard.innerHTML = `
      <strong>${state.currentUser.full_name}</strong><br>
      用户名：${state.currentUser.username}<br>
      电话：${state.currentUser.phone}<br>
      审核状态：${state.currentUser.review_status}<br>
      角色：${state.currentUser.role}
    `;
  }

  registerForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(registerForm).entries());
    try {
      const data = await apiFetch("/api/register", { method: "POST", body: JSON.stringify(payload) });
      registerForm.reset();
      notify(data.message);
    } catch (error) {
      notify(error.message);
    }
  });

  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(loginForm).entries());
    try {
      const data = await apiFetch("/api/login", { method: "POST", body: JSON.stringify(payload) });
      saveToken(data.token);
      state.currentUser = data.user;
      renderGlobalUser();
      notify("登录成功。");
      window.location.reload();
    } catch (error) {
      notify(error.message);
    }
  });

  logoutBtn.addEventListener("click", () => {
    saveToken("");
    state.currentUser = null;
    renderGlobalUser();
    notify("已退出登录。");
    window.location.reload();
  });
}

function analyzeImageData(imageData) {
  const { data } = imageData;
  const pixels = data.length / 4;
  let r = 0, g = 0, b = 0, brightness = 0, variance = 0;
  for (let i = 0; i < data.length; i += 4) {
    const rr = data[i];
    const gg = data[i + 1];
    const bb = data[i + 2];
    const light = 0.299 * rr + 0.587 * gg + 0.114 * bb;
    r += rr;
    g += gg;
    b += bb;
    brightness += light;
  }
  const avgBrightness = brightness / pixels;
  for (let i = 0; i < data.length; i += 4) {
    const light = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
    variance += Math.pow(light - avgBrightness, 2);
  }
  const avgR = r / pixels;
  const avgG = g / pixels;
  const avgB = b / pixels;
  const contrast = Math.sqrt(variance / pixels);
  let dominant = "灰白";
  if (avgR > avgG + 18 && avgR > avgB + 18) dominant = "偏暖/棕橙";
  if (avgG > avgR + 18 && avgG > avgB + 18) dominant = "偏绿";
  if (avgB > avgR + 18 && avgB > avgG + 18) dominant = "偏蓝";
  return {
    brightness: Number(avgBrightness.toFixed(2)),
    contrast: Number(contrast.toFixed(2)),
    average_rgb: [Math.round(avgR), Math.round(avgG), Math.round(avgB)],
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
  const ctx = canvas.getContext("2d", { willReadFrequently: true });

  ctx.filter = "none";
  ctx.drawImage(image, 0, 0, width, height);
  state.rawImage = canvas.toDataURL("image/jpeg", 0.9);
  ctx.filter = "contrast(1.08) saturate(1.08)";
  ctx.drawImage(image, 0, 0, width, height);
  state.processedImage = canvas.toDataURL("image/jpeg", 0.86);
  state.visionReport = analyzeImageData(ctx.getImageData(0, 0, width, height));

  rawPreview.src = state.rawImage;
  processedPreview.src = state.processedImage;
  visionMetrics.textContent = JSON.stringify(state.visionReport, null, 2);
}

function initPublishPage() {
  const startCameraBtn = $("#startCameraBtn");
  const captureBtn = $("#captureBtn");
  const imageFileInput = $("#imageFileInput");
  const cameraPreview = $("#cameraPreview");
  const captureCanvas = $("#captureCanvas");
  const rawPreview = $("#rawPreview");
  const processedPreview = $("#processedPreview");
  const visionMetrics = $("#visionMetrics");
  const petForm = $("#petForm");
  const recognitionCard = $("#recognitionCard");

  startCameraBtn.addEventListener("click", async () => {
    if (state.cameraStream) return;
    try {
      state.cameraStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      cameraPreview.srcObject = state.cameraStream;
    } catch (error) {
      notify(`无法开启摄像头：${error.message}`);
    }
  });

  captureBtn.addEventListener("click", async () => {
    const width = cameraPreview.videoWidth;
    const height = cameraPreview.videoHeight;
    if (!width || !height) {
      notify("请先开启并等待摄像头准备完成。");
      return;
    }
    captureCanvas.width = width;
    captureCanvas.height = height;
    captureCanvas.getContext("2d").drawImage(cameraPreview, 0, 0, width, height);
    await loadImageToCanvas(captureCanvas.toDataURL("image/jpeg", 0.9), captureCanvas, rawPreview, processedPreview, visionMetrics);
  });

  imageFileInput.addEventListener("change", (event) => {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => loadImageToCanvas(reader.result, captureCanvas, rawPreview, processedPreview, visionMetrics);
    reader.readAsDataURL(file);
  });

  petForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.token) {
      notify("请先登录后创建宠物档案。");
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
      recognitionCard.innerHTML = formatRecognition(data.recognition);
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
    fragment.querySelector(".pet-image").src = pet.processed_image_path || pet.image_path || "";
    fragment.querySelector(".pet-name").textContent = pet.name;
    fragment.querySelector(".pet-subtitle").textContent = `${pet.breed || "未填写品种"} · ${pet.found_location || "地点待补充"} · ${pet.created_at}`;
    fragment.querySelector(".pet-description").textContent = pet.description || "暂无描述";
    fragment.querySelector(".pet-state").textContent = pet.recognized_state || pet.status;
    fragment.querySelector(".category-pill").textContent = pet.recognized_category || pet.manual_category || "未分类";
    fragment.querySelector(".creator-pill").textContent = `发布人：${pet.creator_name}`;
    fragment.querySelector(".comment-pill").textContent = `评论 ${pet.comment_count || 0}`;
    fragment.querySelector(".recognition-box").innerHTML = formatRecognition(pet.recognition);

    const commentList = fragment.querySelector(".comment-list");
    const contactList = fragment.querySelector(".contact-list");
    const commentForm = fragment.querySelector(".comment-form");
    const contactForm = fragment.querySelector(".contact-form");
    await loadPetDetails(pet.id, commentList, contactList);

    commentForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!state.token) {
        notify("请先登录后评论。");
        return;
      }
      const payload = Object.fromEntries(new FormData(commentForm).entries());
      try {
        await apiFetch(`/api/pets/${pet.id}/comments`, { method: "POST", body: JSON.stringify(payload) });
        await initPetsPage(true);
      } catch (error) {
        notify(error.message);
      }
    });

    contactForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!state.token) {
        notify("请先登录后提交联系申请。");
        return;
      }
      const payload = Object.fromEntries(new FormData(contactForm).entries());
      try {
        await apiFetch(`/api/pets/${pet.id}/contacts`, { method: "POST", body: JSON.stringify(payload) });
        await loadPetDetails(pet.id, commentList, contactList);
        contactForm.reset();
      } catch (error) {
        notify(error.message);
      }
    });

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
  if (page === "home") await loadHomeStats();
  if (page === "auth") initAuthPage();
  if (page === "publish") initPublishPage();
  if (page === "pets") await initPetsPage();
  if (page === "admin") await initAdminPage();
});
