import { initializeApp } from "https://www.gstatic.com/firebasejs/10.14.1/firebase-app.js";
import {
    getAuth,
    GoogleAuthProvider,
    signInWithPopup,
    setPersistence,
    browserLocalPersistence,
    onAuthStateChanged,
    signOut
} from "https://www.gstatic.com/firebasejs/10.14.1/firebase-auth.js";

const firebaseConfig = {
    apiKey: "AIzaSyBeLNJQTDxGr_I_oP-VwtvMINXqQHkAuOI",
    authDomain: "hypermart-f4e74.firebaseapp.com",
    projectId: "hypermart-f4e74",
    storageBucket: "hypermart-f4e74.firebasestorage.app",
    messagingSenderId: "741818962155",
    appId: "1:741818962155:web:a817d9417da71277bb6eae"
};

const app = initializeApp(firebaseConfig);
const auth = getAuth(app);
const googleProvider = new GoogleAuthProvider();
googleProvider.setCustomParameters({ prompt: "select_account" });

let currentUser = null;
let pendingOpenSellerAfterLogin = false;
let generatedListingDraft = null;

const ORDER_STATUS_OPTIONS = [
    "Order Placed",
    "Order Confirmed",
    "Packed & Ready",
    "Shipped",
    "Out for Delivery",
    "Delivered"
];

const GOOGLE_ICON_SVG = `
  <svg class="w-5 h-5 shrink-0" viewBox="0 0 48 48">
    <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
    <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
    <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
    <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
  </svg>
`;

function fmtINR(n) {
    return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(Number(n) || 0);
}

function showLiveToast(msg, badge = "LIVE UPDATE") {
    const container = document.getElementById("toastContainer");
    if (!container) return;
    const el = document.createElement("div");
    el.className = "pointer-events-auto flex items-center gap-2.5 px-4 py-3 rounded-xl shadow-2xl border border-emerald-400/50 bg-slate-900 text-white text-xs font-semibold animate-fade-up";
    el.innerHTML = `
    <span class="px-2 py-0.5 rounded-md bg-emerald-500 text-slate-950 text-[10px] font-extrabold shrink-0">${badge}</span>
    <span>${msg}</span>
  `;
    container.appendChild(el);
    setTimeout(() => {
        el.style.opacity = "0";
        el.style.transition = "all 0.3s ease";
        setTimeout(() => el.remove(), 300);
    }, 4500);
}

function injectFeatureUI() {
    if (document.getElementById("hypermart-auth-seller-root")) return;
    const wrapper = document.createElement("div");
    wrapper.id = "hypermart-auth-seller-root";
    wrapper.innerHTML = `
    <!-- A. GOOGLE-VERIFIED LOGIN MODAL -->
    <div id="hmLoginOverlay" class="fixed inset-0 z-[9000] hidden items-center justify-center p-4 bg-slate-950/80 backdrop-blur-md">
      <div class="relative w-full max-w-3xl bg-white rounded-2xl shadow-2xl overflow-hidden grid grid-cols-1 md:grid-cols-12 border border-slate-200 animate-fade-up">
        <button type="button" id="closeLoginModalBtn" class="absolute top-3 right-3 z-10 p-1.5 rounded-xl hover:bg-slate-100 text-slate-500">
          <span class="material-symbols-outlined">close</span>
        </button>

        <div class="md:col-span-5 bg-gradient-to-br from-blue-600 to-blue-700 text-white p-8 flex flex-col justify-between min-h-[340px]">
          <div>
            <h2 class="text-2xl font-extrabold tracking-tight">Seller &amp; Account Login</h2>
            <p class="text-sm text-blue-100 mt-3 leading-relaxed">
              Sign in with your verified Google account to access Seller Hub, 3D Model Builder, Seller Admin &amp; Orders.
            </p>
          </div>
          <div class="mt-8 p-4 rounded-xl bg-white/10 border border-white/15 text-xs text-blue-50">
            <div class="font-bold flex items-center gap-1.5">
              <span class="material-symbols-outlined text-base text-emerald-300">verified_user</span>
              <span>Stay Logged In Automatically</span>
            </div>
            <p class="mt-1 text-blue-100/90">Once signed in, your verified Google session stays active across visits.</p>
          </div>
        </div>

        <div class="md:col-span-7 p-8 flex flex-col justify-between gap-6">
          <div>
            <h3 class="text-lg font-extrabold text-slate-900">Sign in to Become a Seller</h3>
            <p class="text-xs text-slate-500 mt-1">Only Google-verified accounts can register &amp; sell on HyperMart.</p>

            <div class="mt-6 flex flex-col gap-3">
              <button type="button" id="googleLoginBtn"
                class="w-full py-3.5 px-4 rounded-xl border-2 border-slate-200 hover:border-blue-500 hover:bg-blue-50/40 bg-white text-slate-900 text-sm font-extrabold flex items-center justify-center gap-3 shadow-sm transition-all">
                ${GOOGLE_ICON_SVG}
                <span>Continue with Google</span>
              </button>
              <p id="hmLoginError" class="hidden text-xs font-semibold text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2"></p>
            </div>
          </div>

          <p class="text-[11px] text-slate-400">
            By continuing, you agree to HyperMart's Terms of Use &amp; Seller Privacy Policy.
          </p>
        </div>
      </div>
    </div>

    <!-- B. ACCOUNT PROFILE TRAY DROPDOWN -->
    <div id="hmAccountTray"
      class="hidden fixed top-[74px] right-4 sm:right-6 z-[8000] w-72 bg-white rounded-2xl shadow-2xl border border-slate-200 py-2 animate-fade-up">
      <div class="px-4 py-3 border-b border-slate-100">
        <div class="text-xs font-extrabold text-slate-900">Your Account</div>
        <div id="hmTrayUserName" class="text-xs font-bold text-primary truncate mt-0.5">Guest</div>
        <div id="hmTrayUserEmail" class="text-[11px] text-slate-500 truncate">Not signed in</div>
      </div>
      <div class="py-1 text-xs font-semibold text-slate-700">
        <button type="button" data-tray="profile" class="w-full px-4 py-2.5 hover:bg-slate-50 flex items-center gap-3 text-left"><span class="material-symbols-outlined text-lg text-slate-500">account_circle</span><span>My Profile</span></button>
        <button type="button" data-tray="orders" class="w-full px-4 py-2.5 hover:bg-slate-50 flex items-center gap-3 text-left"><span class="material-symbols-outlined text-lg text-slate-500">inventory_2</span><span>Orders (Live Status)</span></button>
        <button type="button" data-tray="wishlist" class="w-full px-4 py-2.5 hover:bg-slate-50 flex items-center gap-3 text-left"><span class="material-symbols-outlined text-lg text-slate-500">favorite</span><span>Wishlist</span></button>
        <button type="button" data-tray="seller" class="w-full px-4 py-2.5 bg-amber-50/70 hover:bg-amber-100/80 text-amber-900 font-extrabold flex items-center gap-3 text-left border-t border-amber-200/70 mt-1">
          <span class="material-symbols-outlined text-lg text-amber-600">storefront</span>
          <span>Become a Seller / Hub</span>
        </button>
        <button type="button" data-tray="seller-admin" class="w-full px-4 py-2.5 bg-blue-50/70 hover:bg-blue-100/80 text-blue-900 font-extrabold flex items-center gap-3 text-left border-b border-blue-200/70 mb-1">
          <span class="material-symbols-outlined text-lg text-primary">analytics</span>
          <span>Seller Admin &amp; Reports</span>
        </button>
        <button type="button" id="hmTrayAuthBtn" data-tray="auth" class="w-full px-4 py-2.5 hover:bg-slate-50 text-primary flex items-center gap-3 text-left">
          <span class="material-symbols-outlined text-lg">login</span><span>Login with Google</span>
        </button>
      </div>
    </div>

    <!-- C. SELLER PORTAL FULL-SCREEN MODAL -->
    <div id="hmSellerModal" class="fixed inset-0 z-[8500] hidden bg-slate-50 overflow-y-auto">
      <div class="sticky top-0 z-20 bg-white border-b border-slate-200 px-4 sm:px-8 py-3.5 flex flex-wrap items-center justify-between gap-3">
        <div class="flex items-center gap-3">
          <div class="h-8 w-8 rounded-lg bg-amber-400 text-slate-900 font-extrabold text-xs flex items-center justify-center">HM</div>
          <span class="font-extrabold text-slate-900 text-base">Sell on <span class="text-primary">HyperMart</span></span>
        </div>

        <div id="sellerTopTabs" class="flex items-center gap-1.5 bg-slate-100 p-1 rounded-xl">
          <button type="button" id="tabListProductBtn" class="px-3.5 py-1.5 rounded-lg bg-white text-primary shadow-sm text-xs font-extrabold flex items-center gap-1.5">
            <span class="material-symbols-outlined text-base">add_box</span><span>List Product</span>
          </button>
          <button type="button" id="tabSellerAdminBtn" class="px-3.5 py-1.5 rounded-lg text-slate-600 hover:text-slate-900 text-xs font-bold flex items-center gap-1.5">
            <span class="material-symbols-outlined text-base">analytics</span><span>Seller Admin &amp; Orders</span>
          </button>
        </div>

        <div class="flex items-center gap-3">
          <button type="button" id="hmSellerStartTopBtn" class="px-5 py-2 rounded-xl bg-amber-400 hover:bg-amber-500 text-slate-950 text-xs font-extrabold shadow-sm transition-colors">+ New Listing</button>
          <button type="button" id="hmCloseSellerModal" class="p-2 rounded-xl hover:bg-slate-100 text-slate-600">
            <span class="material-symbols-outlined">close</span>
          </button>
        </div>
      </div>

      <!-- VIEW 1: SELLER HUB (PRODUCT LISTING + 3D MODEL GENERATOR) -->
      <div id="sellerViewHub" class="max-w-5xl mx-auto px-4 py-8 flex flex-col gap-6">
        <div class="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm">
          <div class="flex flex-wrap items-center justify-between gap-2 pb-4 border-b border-slate-100">
            <div>
              <h2 class="text-xl font-extrabold text-slate-900">HyperMart Seller Hub</h2>
              <p class="text-xs text-slate-500 mt-0.5">Upload clean photos of all 6 sides to generate your Dashboard Listing Image and Interactive 3D Model. Test both below before submitting.</p>
            </div>
            <span id="hubSellerBadge" class="px-3 py-1 rounded-full bg-emerald-100 text-emerald-800 text-xs font-extrabold">Verified Seller</span>
          </div>

          <form id="sellerGenerateForm" class="mt-5 flex flex-col gap-5">
            <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
              <input id="upName" type="text" required placeholder="Product Name *" class="lg:col-span-2 h-10 rounded-xl border-slate-300 text-xs font-semibold" />
              <select id="upCategory" class="h-10 rounded-xl border-slate-300 text-xs font-semibold">
                <option value="Accessories">Accessories</option>
                <option value="Fashion">Fashion</option>
                <option value="Audio">Audio</option>
                <option value="Wearables">Wearables</option>
                <option value="Displays">Displays</option>
                <option value="Furniture">Furniture</option>
                <option value="Smartphones">Smartphones</option>
                <option value="Laptops">Laptops</option>
              </select>
              <input id="upPrice" type="number" required min="1" placeholder="Price (₹) *" class="h-10 rounded-xl border-slate-300 text-xs font-semibold" />
              <input id="upStock" type="number" required min="1" value="10" placeholder="Stock *" class="h-10 rounded-xl border-slate-300 text-xs font-semibold" />
            </div>

            <div>
              <div class="text-xs font-extrabold text-slate-800 mb-2">Upload Clean Photos of All 6 Product Sides (Used for 3D Model &amp; Saved in DB)</div>
              <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
                ${["front", "back", "left", "right", "top", "bottom"].map((side) => `
                  <label class="cursor-pointer border-2 border-dashed border-slate-300 hover:border-primary rounded-xl p-3 flex flex-col items-center justify-center gap-1.5 bg-slate-50 text-center">
                    <span class="material-symbols-outlined text-primary text-2xl">add_a_photo</span>
                    <span class="text-[11px] font-extrabold text-slate-800 capitalize">${side === "bottom" ? "Down / Bottom" : side} View ${side === "front" ? "*" : ""}</span>
                    <span id="lbl_${side}" class="text-[10px] text-slate-400 truncate max-w-full">Choose photo</span>
                    <input type="file" name="${side}" accept="image/*" ${side === "front" ? "required" : ""} class="hidden seller-view-input" data-side="${side}" />
                  </label>
                `).join("")}
              </div>
            </div>

            <button type="submit" id="sellerGenerateBtn"
              class="py-3.5 px-6 rounded-xl bg-primary hover:bg-primary-hover text-white text-sm font-extrabold shadow-md flex items-center justify-center gap-2">
              <span class="material-symbols-outlined text-lg">view_in_ar</span>
              <span>Generate Listing Image &amp; 3D Model</span>
            </button>
          </form>

          <!-- PREVIEW PANEL AT BOTTOM: DASHBOARD LISTING IMAGE + INTERACTIVE 3D MODEL TESTER -->
          <div id="aiPreviewPanel" class="hidden mt-6 pt-6 border-t border-slate-200 animate-fade-up">
            <div class="flex flex-wrap items-center justify-between gap-2 mb-4">
              <h3 class="text-sm font-extrabold text-slate-900 flex items-center gap-1.5">
                <span class="material-symbols-outlined text-primary text-lg">verified</span>
                <span>Preview Dashboard Listing Image &amp; Test Generated 3D Model</span>
              </h3>
              <span class="text-[11px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 px-2.5 py-0.5 rounded-full">Ready to Publish</span>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-2 gap-5">
              <div class="rounded-2xl border border-slate-200 bg-slate-50/80 p-4 flex flex-col justify-between gap-3">
                <div class="text-xs font-extrabold text-slate-700">1. HyperMart Dashboard Listing Image</div>
                <div class="bg-white rounded-xl border border-slate-200 p-4 flex items-center justify-center h-64">
                  <img id="aiGeneratedPreview" src="" alt="Dashboard Listing Image" class="max-h-full max-w-full object-contain rounded-lg" />
                </div>
                <div class="flex items-center justify-between pt-1">
                  <div>
                    <span id="previewCat" class="text-[10px] font-extrabold uppercase tracking-wider text-primary">ACCESSORIES</span>
                    <h4 id="previewName" class="text-base font-extrabold text-slate-900">Product Name</h4>
                  </div>
                  <div class="text-right">
                    <div id="previewPrice" class="text-lg font-extrabold text-slate-900 tabular-nums">₹0</div>
                    <span id="previewStock" class="px-2 py-0.5 rounded-md bg-amber-100 text-amber-800 text-[10px] font-extrabold">10 In Stock</span>
                  </div>
                </div>
              </div>

              <div class="rounded-2xl border border-slate-200 bg-slate-900 p-4 flex flex-col justify-between gap-3">
                <div class="flex items-center justify-between">
                  <span class="text-xs font-extrabold text-white flex items-center gap-1.5">
                    <span class="material-symbols-outlined text-blue-400 text-base">3d_rotation</span>
                    <span>2. Interactive 3D Model (Drag 360° &amp; Zoom to Test)</span>
                  </span>
                  <span class="text-[10px] font-bold text-blue-300 bg-blue-500/20 px-2 py-0.5 rounded-full">.GLB Ready</span>
                </div>
                <div class="rounded-xl overflow-hidden bg-gradient-to-br from-slate-950 via-slate-900 to-indigo-950 border border-white/10 h-64">
                  <model-viewer id="seller3dPreview" camera-controls auto-rotate shadow-intensity="1.1"
                    exposure="1.1" environment-image="neutral"
                    style="width: 100%; height: 100%; background: transparent;">
                  </model-viewer>
                </div>
                <div class="text-[11px] text-slate-300">
                  Buyers will interact with this exact 3D model when they click your product on the HyperMart dashboard.
                </div>
              </div>
            </div>

            <div class="mt-5">
              <button type="button" id="submitListingBtn"
                class="w-full py-3.5 px-6 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-extrabold shadow-md flex items-center justify-center gap-2 transition-colors">
                <span class="material-symbols-outlined text-lg">publish</span>
                <span>Submit Listing &amp; 3D Model to HyperMart Store</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- VIEW 2: SELLER ADMIN (SELLING REPORT + ORDERS + LIVE STATUS UPDATES + LISTED PRODUCTS) -->
      <div id="sellerViewAdmin" class="hidden max-w-6xl mx-auto px-4 py-8 flex flex-col gap-6">
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div class="bg-white rounded-2xl p-5 border border-slate-200 shadow-sm">
            <div class="text-xs font-bold text-slate-500">Total Revenue</div>
            <div id="adminTotalRevenue" class="text-2xl font-extrabold text-emerald-600 mt-1 tabular-nums">₹0</div>
          </div>
          <div class="bg-white rounded-2xl p-5 border border-slate-200 shadow-sm">
            <div class="text-xs font-bold text-slate-500">Total Orders</div>
            <div id="adminTotalOrders" class="text-2xl font-extrabold text-slate-900 mt-1 tabular-nums">0</div>
          </div>
          <div class="bg-white rounded-2xl p-5 border border-slate-200 shadow-sm">
            <div class="text-xs font-bold text-slate-500">Units Sold</div>
            <div id="adminTotalUnits" class="text-2xl font-extrabold text-primary mt-1 tabular-nums">0</div>
          </div>
          <div class="bg-white rounded-2xl p-5 border border-slate-200 shadow-sm">
            <div class="text-xs font-bold text-slate-500">Listed Products</div>
            <div id="adminTotalProducts" class="text-2xl font-extrabold text-amber-600 mt-1 tabular-nums">0</div>
          </div>
        </div>

        <div class="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm">
          <div class="flex items-center justify-between pb-4 border-b border-slate-100">
            <div>
              <h3 class="text-base font-extrabold text-slate-900">Customer Orders &amp; Live Status Control</h3>
              <p class="text-xs text-slate-500 mt-0.5">Updating an order status immediately sends a live real-time notification to the buyer.</p>
            </div>
            <button type="button" id="refreshAdminReportBtn" class="px-3 py-1.5 rounded-xl bg-slate-100 hover:bg-slate-200 text-xs font-bold text-slate-800 flex items-center gap-1">
              <span class="material-symbols-outlined text-base">refresh</span><span>Refresh</span>
            </button>
          </div>
          <div id="adminOrdersTable" class="mt-4 flex flex-col gap-3"></div>
        </div>

        <div class="bg-white rounded-2xl p-6 border border-slate-200 shadow-sm">
          <h3 class="text-base font-extrabold text-slate-900 pb-4 border-b border-slate-100">Listed Products Inventory</h3>
          <div id="adminProductsGrid" class="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3"></div>
        </div>
      </div>
    </div>
  `;
    document.body.appendChild(wrapper);
}

function openLoginModal() {
    const overlay = document.getElementById("hmLoginOverlay");
    if (!overlay) return;
    document.getElementById("hmLoginError")?.classList.add("hidden");
    overlay.classList.remove("hidden");
    overlay.classList.add("flex");
}

function closeLoginModal() {
    const overlay = document.getElementById("hmLoginOverlay");
    if (!overlay) return;
    overlay.classList.add("hidden");
    overlay.classList.remove("flex");
}

async function performGoogleSignIn() {
    await setPersistence(auth, browserLocalPersistence);
    const res = await signInWithPopup(auth, googleProvider);
    if (!res.user.emailVerified) {
        await signOut(auth);
        throw new Error("Only Google-verified accounts are allowed to login.");
    }
    currentUser = res.user;
    updateProfileUI(currentUser);
    return res.user;
}

function updateProfileUI(user) {
    const profileImg = document.querySelector("#profileBtn img");
    if (user && profileImg && user.photoURL) profileImg.src = user.photoURL;
    const nameEl = document.getElementById("hmTrayUserName");
    const emailEl = document.getElementById("hmTrayUserEmail");
    const authBtn = document.getElementById("hmTrayAuthBtn");

    if (nameEl) nameEl.textContent = user ? (user.displayName || "Verified User") : "Guest";
    if (emailEl) emailEl.textContent = user ? user.email : "Not signed in";
    if (authBtn) {
        authBtn.innerHTML = user
            ? `<span class="material-symbols-outlined text-lg">logout</span><span>Logout</span>`
            : `<span class="material-symbols-outlined text-lg">login</span><span>Login with Google</span>`;
        authBtn.className = user
            ? "w-full px-4 py-2.5 hover:bg-rose-50 text-rose-600 flex items-center gap-3 text-left"
            : "w-full px-4 py-2.5 hover:bg-blue-50 text-primary flex items-center gap-3 text-left";
    }
}

function resetListingForm() {
    document.getElementById("sellerGenerateForm")?.reset();
    ["front", "back", "left", "right", "top", "bottom"].forEach((s) => {
        const lbl = document.getElementById(`lbl_${s}`);
        if (lbl) lbl.textContent = "Choose photo";
    });
    document.getElementById("aiPreviewPanel")?.classList.add("hidden");
    document.getElementById("seller3dPreview")?.removeAttribute("src");
    generatedListingDraft = null;
}

function showSellerView(viewId) {
    document.getElementById("sellerViewHub")?.classList.toggle("hidden", viewId !== "sellerViewHub");
    document.getElementById("sellerViewAdmin")?.classList.toggle("hidden", viewId !== "sellerViewAdmin");

    const listBtn = document.getElementById("tabListProductBtn");
    const adminBtn = document.getElementById("tabSellerAdminBtn");
    if (listBtn && adminBtn) {
        listBtn.className = viewId === "sellerViewHub"
            ? "px-3.5 py-1.5 rounded-lg bg-white text-primary shadow-sm text-xs font-extrabold flex items-center gap-1.5"
            : "px-3.5 py-1.5 rounded-lg text-slate-600 hover:text-slate-900 text-xs font-bold flex items-center gap-1.5";
        adminBtn.className = viewId === "sellerViewAdmin"
            ? "px-3.5 py-1.5 rounded-lg bg-white text-primary shadow-sm text-xs font-extrabold flex items-center gap-1.5"
            : "px-3.5 py-1.5 rounded-lg text-slate-600 hover:text-slate-900 text-xs font-bold flex items-center gap-1.5";
    }

    if (viewId === "sellerViewAdmin") loadSellerAdminReport();
}

function openSellerFlow(targetView = "sellerViewHub") {
    if (!currentUser) {
        pendingOpenSellerAfterLogin = targetView;
        openLoginModal();
        return;
    }
    document.getElementById("hmSellerModal")?.classList.remove("hidden");
    localStorage.setItem("hypermart_seller_email", currentUser.email);
    const badge = document.getElementById("hubSellerBadge");
    if (badge) badge.textContent = `Seller: ${currentUser.displayName || currentUser.email}`;
    showSellerView(targetView);
}

async function loadSellerAdminReport() {
    const ordersBox = document.getElementById("adminOrdersTable");
    const productsBox = document.getElementById("adminProductsGrid");
    if (ordersBox) ordersBox.innerHTML = `<div class="text-xs text-slate-500">Loading selling report &amp; orders...</div>`;

    try {
        const res = await fetch("/api/seller/admin/report");
        const data = await res.json();
        if (!res.ok || !data.success) throw new Error(data.message || "Failed to load report");

        document.getElementById("adminTotalRevenue").textContent = fmtINR(data.summary.total_revenue);
        document.getElementById("adminTotalOrders").textContent = String(data.summary.total_orders);
        document.getElementById("adminTotalUnits").textContent = String(data.summary.total_units_sold);
        document.getElementById("adminTotalProducts").textContent = String(data.summary.total_products);

        ordersBox.innerHTML = data.orders.length
            ? data.orders.map((o) => `
          <div class="p-4 rounded-xl border border-slate-200 bg-slate-50/70 flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div class="flex items-center gap-3 min-w-0">
              <img src="${o.image_url}" alt="${o.product_name}" class="w-12 h-12 rounded-xl object-contain bg-white border border-slate-200 p-1 shrink-0" />
              <div class="min-w-0">
                <div class="text-xs font-extrabold text-slate-900 truncate">#HM-${o.id} · ${o.product_name} (×${o.quantity})</div>
                <div class="text-[11px] text-slate-500 mt-0.5">${fmtINR(o.total)} · ${new Date(o.order_date).toLocaleString("en-IN")}</div>
              </div>
            </div>
            <div class="flex flex-wrap items-center gap-2 shrink-0">
              <select data-status-select="${o.id}" class="h-9 rounded-xl border-slate-300 text-xs font-bold text-slate-800">
                ${ORDER_STATUS_OPTIONS.map((st) => `<option value="${st}" ${st === o.status ? "selected" : ""}>${st}</option>`).join("")}
              </select>
              <button type="button" data-update-order="${o.id}" class="px-3.5 h-9 rounded-xl bg-primary hover:bg-primary-hover text-white text-xs font-extrabold shadow-sm">
                Update Status
              </button>
            </div>
          </div>
        `).join("")
            : `<div class="text-xs text-slate-500 py-6 text-center">No customer orders yet.</div>`;

        productsBox.innerHTML = data.products.map((p) => `
      <div class="p-3 rounded-xl border border-slate-200 bg-slate-50/60 flex items-center gap-3">
        <img src="${p.image_url}" alt="${p.name}" class="w-12 h-12 rounded-lg object-contain bg-white border border-slate-200 p-1 shrink-0" />
        <div class="min-w-0 flex-1">
          <div class="text-xs font-extrabold text-slate-900 truncate">${p.name}</div>
          <div class="text-[11px] text-slate-500">${p.category} · ${fmtINR(p.price)} · <span class="font-bold text-emerald-700">${p.stock} in stock</span></div>
        </div>
      </div>
    `).join("");
    } catch (err) {
        if (ordersBox) ordersBox.innerHTML = `<div class="text-xs text-rose-600">${err.message}</div>`;
    }
}

function setupLiveOrderStatusUpdates() {
    if (typeof io === "undefined") return;
    const socket = io();
    socket.on("order_status_updated", (evt) => {
        showLiveToast(`Order #HM-${evt.orderId} (${evt.productName}) is now "${evt.status}"`, "ORDER UPDATE");
        const utilModal = document.getElementById("utilityModal");
        const utilTitle = document.getElementById("utilityModalTitle")?.textContent || "";
        if (utilModal && !utilModal.classList.contains("hidden") && utilTitle.includes("Orders")) {
            document.getElementById("openOrdersBtn")?.click();
        }
    });
}

function hookBuyerOrdersStatusSync() {
    document.getElementById("openOrdersBtn")?.addEventListener("click", () => {
        setTimeout(async () => {
            try {
                const res = await fetch("/api/orders/statuses");
                const statuses = await res.json();
                const body = document.getElementById("utilityModalBody");
                if (!body) return;
                body.querySelectorAll("div").forEach((card) => {
                    const match = card.textContent.match(/#HM-(\d+)/);
                    if (match && statuses[match[1]]) {
                        const badge = card.querySelector("span.rounded-full");
                        if (badge) badge.textContent = statuses[match[1]];
                    }
                });
            } catch (_) { }
        }, 350);
    });
}

function bindFeatureEvents() {
    document.getElementById("closeLoginModalBtn")?.addEventListener("click", () => {
        pendingOpenSellerAfterLogin = false;
        closeLoginModal();
    });

    document.getElementById("googleLoginBtn")?.addEventListener("click", async () => {
        const errEl = document.getElementById("hmLoginError");
        errEl?.classList.add("hidden");
        try {
            await performGoogleSignIn();
            closeLoginModal();
            if (pendingOpenSellerAfterLogin) {
                const target = typeof pendingOpenSellerAfterLogin === "string" ? pendingOpenSellerAfterLogin : "sellerViewHub";
                pendingOpenSellerAfterLogin = false;
                openSellerFlow(target);
            }
        } catch (err) {
            if (errEl) {
                errEl.textContent = err.message || "Google Sign-In failed.";
                errEl.classList.remove("hidden");
            }
        }
    });

    // Profile Tray Toggle (event delegation so it never misses a click)
    document.addEventListener("click", (e) => {
        const tray = document.getElementById("hmAccountTray");
        if (!tray) return;
        if (e.target.closest("#profileBtn")) {
            e.stopPropagation();
            tray.classList.toggle("hidden");
            return;
        }
        if (!e.target.closest("#hmAccountTray")) {
            tray.classList.add("hidden");
        }
    });

    document.getElementById("hmAccountTray")?.addEventListener("click", async (e) => {
        const btn = e.target.closest("[data-tray]");
        if (!btn) return;
        document.getElementById("hmAccountTray")?.classList.add("hidden");
        const act = btn.dataset.tray;

        if (act === "orders") document.getElementById("openOrdersBtn")?.click();
        if (act === "wishlist") document.getElementById("openWishlistBtn")?.click();
        if (act === "seller") openSellerFlow("sellerViewHub");
        if (act === "seller-admin") openSellerFlow("sellerViewAdmin");
        if (act === "auth") {
            if (currentUser) {
                await signOut(auth);
                localStorage.removeItem("hypermart_seller_email");
                currentUser = null;
                updateProfileUI(null);
            } else {
                pendingOpenSellerAfterLogin = false;
                openLoginModal();
            }
        }
    });

    document.querySelector('[data-action="open-seller"]')?.addEventListener("click", () => openSellerFlow("sellerViewHub"));
    document.getElementById("hmCloseSellerModal")?.addEventListener("click", () => {
        document.getElementById("hmSellerModal")?.classList.add("hidden");
    });

    document.getElementById("tabListProductBtn")?.addEventListener("click", () => showSellerView("sellerViewHub"));
    document.getElementById("tabSellerAdminBtn")?.addEventListener("click", () => showSellerView("sellerViewAdmin"));
    document.getElementById("refreshAdminReportBtn")?.addEventListener("click", loadSellerAdminReport);

    document.getElementById("hmSellerStartTopBtn")?.addEventListener("click", () => {
        showSellerView("sellerViewHub");
        resetListingForm();
        document.getElementById("hmSellerModal")?.scrollTo({ top: 0, behavior: "smooth" });
        document.getElementById("upName")?.focus();
    });

    document.getElementById("adminOrdersTable")?.addEventListener("click", async (e) => {
        const btn = e.target.closest("[data-update-order]");
        if (!btn) return;
        const orderId = btn.dataset.updateOrder;
        const sel = document.querySelector(`[data-status-select="${orderId}"]`);
        const status = sel ? sel.value : "Order Confirmed";

        btn.disabled = true;
        btn.textContent = "Updating...";
        try {
            const res = await fetch("/api/seller/admin/order-status", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ order_id: Number(orderId), status })
            });
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error(data.message || "Update failed");
            showLiveToast(`Updated #HM-${orderId} to "${status}"`, "SAVED");
        } catch (err) {
            alert(err.message);
        } finally {
            btn.disabled = false;
            btn.textContent = "Update Status";
        }
    });

    document.querySelectorAll(".seller-view-input").forEach((inp) => {
        inp.addEventListener("change", () => {
            const lbl = document.getElementById(`lbl_${inp.dataset.side}`);
            if (lbl && inp.files[0]) lbl.textContent = inp.files[0].name;
        });
    });

    document.getElementById("sellerGenerateForm")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const btn = document.getElementById("sellerGenerateBtn");
        btn.disabled = true;
        btn.innerHTML = `<span class="material-symbols-outlined animate-spin">progress_activity</span><span>Generating Listing Image &amp; 3D Model...</span>`;

        try {
            const name = document.getElementById("upName").value.trim();
            const category = document.getElementById("upCategory").value;
            const price = Number(document.getElementById("upPrice").value);
            const stock = Number(document.getElementById("upStock").value);

            const fd = new FormData(e.target);
            fd.append("name", name);
            fd.append("category", category);

            const res = await fetch("/api/seller/generate-preview", { method: "POST", body: fd });
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error(data.message || "Generation failed");

            generatedListingDraft = {
                name,
                category,
                price,
                stock,
                city: "Bengaluru",
                seller_email: localStorage.getItem("hypermart_seller_email") || currentUser?.email || "",
                ai_image_url: data.ai_image_url,
                model_url: data.model_url,
                saved_views: data.saved_views
            };

            document.getElementById("aiGeneratedPreview").src = data.ai_image_url;
            document.getElementById("seller3dPreview").src = data.model_url;
            document.getElementById("previewCat").textContent = category;
            document.getElementById("previewName").textContent = name;
            document.getElementById("previewPrice").textContent = fmtINR(price);
            document.getElementById("previewStock").textContent = `${stock} In Stock`;

            const panel = document.getElementById("aiPreviewPanel");
            panel.classList.remove("hidden");
            panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
        } catch (err) {
            alert(err.message);
        } finally {
            btn.disabled = false;
            btn.innerHTML = `<span class="material-symbols-outlined text-lg">view_in_ar</span><span>Generate Listing Image &amp; 3D Model</span>`;
        }
    });

    document.getElementById("submitListingBtn")?.addEventListener("click", async () => {
        if (!generatedListingDraft) return;
        const btn = document.getElementById("submitListingBtn");
        btn.disabled = true;
        btn.innerHTML = `<span class="material-symbols-outlined animate-spin">progress_activity</span><span>Publishing Listing &amp; 3D Model...</span>`;

        try {
            const res = await fetch("/api/seller/submit-listing", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(generatedListingDraft)
            });
            const data = await res.json();
            if (!res.ok || !data.success) throw new Error(data.message || "Failed to submit listing");

            resetListingForm();
            document.getElementById("hmSellerModal")?.classList.add("hidden");
            document.getElementById("brandHomeBtn")?.click();
            showLiveToast("Product & interactive 3D model published to HyperMart!", "LIVE");
        } catch (err) {
            alert(err.message);
        } finally {
            btn.disabled = false;
            btn.innerHTML = `<span class="material-symbols-outlined text-lg">publish</span><span>Submit Listing &amp; 3D Model to HyperMart Store</span>`;
        }
    });
}

function initFeatures() {
    injectFeatureUI();
    bindFeatureEvents();
    setupLiveOrderStatusUpdates();
    hookBuyerOrdersStatusSync();

    onAuthStateChanged(auth, (user) => {
        if (user && user.emailVerified) {
            currentUser = user;
            updateProfileUI(user);
        } else {
            currentUser = null;
            updateProfileUI(null);
        }
    });
}

if (document.readyState === "loading") {
    window.addEventListener("DOMContentLoaded", initFeatures);
} else {
    initFeatures();
}