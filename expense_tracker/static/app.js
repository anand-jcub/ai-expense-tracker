/* SPA Tab switching, Chart.js rendering, Theme Toggle, Scroll & Filter preservation */
(function () {
  'use strict';

  var FILTER_KEYS = [
    'start_date', 'end_date', 'exclude_business', 'use_my_share',
    'review_sort', 'review_search', 'edit_search', 'person_search', 'exclude_credits', 'tx_filter'
  ];

  /* ── Diagnostic Global Error Logger ── */
  window.addEventListener('error', function (event) {
    var msg = event.message || (event.error && event.error.message) || 'Unknown error';
    console.error("Uncaught JS error:", event);
    showToast("JS Error: " + msg, true);
  });

  /* ── Tab Navigation Control ── */
  var tabs = document.querySelectorAll('.tab-link');
  var panes = document.querySelectorAll('.tab-pane');

  function switchTab(tabId) {
    if (!tabId) return;
    tabs.forEach(function (tab) {
      if (tab.getAttribute('data-tab') === tabId) {
        tab.classList.add('active');
      } else {
        tab.classList.remove('active');
      }
    });

    panes.forEach(function (pane) {
      if (pane.id === 'pane-' + tabId) {
        pane.classList.add('active');
      } else {
        pane.classList.remove('active');
      }
    });
    
    // Store active tab
    sessionStorage.setItem('_active_tab', tabId);

    // Update URL hash without jumping/scrolling into content under the fixed header
    if (history.pushState) {
      history.pushState(null, null, '#' + tabId);
    } else {
      location.hash = '#' + tabId;
    }

    // Always start tabs below the fixed "Personal Expense Tracker" header
    try {
      window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
      document.documentElement.scrollTop = 0;
      document.body.scrollTop = 0;
    } catch (err) {
      window.scrollTo(0, 0);
    }
    
    // Redraw charts when switching to the dashboard tab so they size correctly
    if (tabId === 'dashboard') {
      try {
        if (typeof Chart !== 'undefined') {
          renderCharts();
        }
      } catch (err) {
        console.error("Chart redraw failed on tab switch:", err);
        showToast("Chart Switch Error: " + err.message, true);
      }
    }
  }

  tabs.forEach(function (tab) {
    tab.addEventListener('click', function (e) {
      e.preventDefault();
      var tabId = tab.getAttribute('data-tab');
      switchTab(tabId);
    });
  });

  // Init tab selection on load
  var initialTab = location.hash ? location.hash.slice(1) : (sessionStorage.getItem('_active_tab') || 'dashboard');
  if (initialTab === 'person-search') initialTab = 'search';
  if (initialTab === 'transactions' || initialTab === 'edit-classifications') initialTab = 'review';
  if (initialTab === 'merchant-rules' || initialTab === 'shared-expenses') initialTab = 'rules';
  switchTab(initialTab);

  // Sync tab switching on hash change
  window.addEventListener('hashchange', function () {
    var hash = location.hash.slice(1);
    if (hash === 'person-search') hash = 'search';
    if (hash === 'transactions' || hash === 'edit-classifications') hash = 'review';
    if (hash === 'merchant-rules' || hash === 'shared-expenses') hash = 'rules';
    if (hash) switchTab(hash);
  });

  /* ── Theme Handling ── */
  var themeToggle = document.getElementById('theme-toggle');
  
  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
    if (themeToggle) {
      themeToggle.setAttribute('aria-label', 'Switch to ' + (theme === 'dark' ? 'light' : 'dark') + ' mode');
      var moonIcon = themeToggle.querySelector('.moon-icon');
      var sunIcon = themeToggle.querySelector('.sun-icon');
      if (moonIcon && sunIcon) {
        if (theme === 'dark') {
          moonIcon.style.display = 'none';
          sunIcon.style.display = 'block';
        } else {
          moonIcon.style.display = 'block';
          sunIcon.style.display = 'none';
        }
      }
    }
  }

  var savedTheme = localStorage.getItem('theme') || 'dark';
  applyTheme(savedTheme);

  if (themeToggle) {
    themeToggle.addEventListener('click', function () {
      var currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
      applyTheme(currentTheme === 'dark' ? 'light' : 'dark');
      try {
        if (typeof Chart !== 'undefined') {
          renderCharts();
        }
      } catch (err) {
        showToast("Theme Chart Error: " + err.message, true);
      }
    });
  }

  /* ── Toast Notification Engine ── */
  var toastContainer = document.getElementById('toast-container');
  if (toastContainer) {
    var message = toastContainer.getAttribute('data-message');
    var error = toastContainer.getAttribute('data-error');
    if (message || error) {
      showToast(message || error, !!error);
    }
  }

  function showToast(text, isError) {
    var toast = document.createElement('div');
    toast.className = 'toast ' + (isError ? 'error' : 'success');
    toast.textContent = text;
    
    var closeBtn = document.createElement('span');
    closeBtn.className = 'toast-close';
    closeBtn.innerHTML = '&times;';
    closeBtn.onclick = function () { toast.remove(); };
    toast.appendChild(closeBtn);

    var container = document.getElementById('toast-container');
    if (container) {
      container.appendChild(toast);
      setTimeout(function () {
        toast.classList.add('show');
      }, 50);

      // Auto dismiss
      setTimeout(function () {
        toast.classList.remove('show');
        setTimeout(function () { toast.remove(); }, 400);
      }, 4500);
    }
  }

  /* ── Chart.js Rendering Engine ── */
  function renderCharts() {
    var isDark = (document.documentElement.getAttribute('data-theme') || 'dark') === 'dark';
    var textMuted = isDark ? '#94a3b8' : '#64748b';
    var gridColor = isDark ? 'rgba(34, 46, 67, 0.5)' : 'rgba(226, 232, 240, 0.5)';
    var successColor = isDark ? '#10b981' : '#059669';
    var errorColor = isDark ? '#ef4444' : '#dc2626';
    var accentColor = isDark ? '#6366f1' : '#4f46e5';

    // Custom inline plugin to draw bar values next to horizontal bars
    var inlineDataLabels = {
      id: 'inlineDataLabels',
      afterDatasetsDraw: function (chart) {
        var ctx = chart.ctx;
        var isDark = (document.documentElement.getAttribute('data-theme') || 'dark') === 'dark';
        ctx.save();
        ctx.font = 'bold 11px Inter';
        ctx.fillStyle = isDark ? '#e2e8f0' : '#1e293b';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';

        chart.data.datasets.forEach(function (dataset, datasetIndex) {
          var meta = chart.getDatasetMeta(datasetIndex);
          meta.data.forEach(function (bar, index) {
            var value = dataset.data[index];
            if (value > 0) {
              var formatted = '₹' + value.toLocaleString('en-IN', { minimumFractionDigits: 2 });
              ctx.fillText(formatted, bar.x + 8, bar.y);
            }
          });
        });
        ctx.restore();
      }
    };

    // 1. Monthly Spend Trend Line Chart
    var trendCanvas = document.getElementById('monthlyTrendChart');
    if (trendCanvas) {
      var existing = Chart.getChart(trendCanvas);
      if (existing) existing.destroy();

      var activeTab = 'expenses';
      if (document.getElementById('card-credits') && document.getElementById('card-credits').classList.contains('active')) {
        activeTab = 'credits';
      } else if (document.getElementById('card-debits') && document.getElementById('card-debits').classList.contains('active')) {
        activeTab = 'debits';
      }

      var trendLabels = JSON.parse(trendCanvas.getAttribute('data-labels-' + activeTab) || '[]');
      var trendValues = JSON.parse(trendCanvas.getAttribute('data-values-' + activeTab) || '[]');

      var lineColor = accentColor;
      var areaBg = isDark ? 'rgba(99, 102, 241, 0.18)' : 'rgba(79, 70, 229, 0.12)';
      if (activeTab === 'credits') {
        lineColor = successColor;
        areaBg = isDark ? 'rgba(16, 185, 129, 0.18)' : 'rgba(5, 150, 105, 0.12)';
      } else if (activeTab === 'debits') {
        lineColor = errorColor;
        areaBg = isDark ? 'rgba(239, 68, 68, 0.18)' : 'rgba(220, 38, 38, 0.12)';
      }

      new Chart(trendCanvas, {
        type: 'line',
        data: {
          labels: trendLabels,
          datasets: [{
            data: trendValues,
            borderColor: lineColor,
            backgroundColor: areaBg,
            borderWidth: 3,
            fill: true,
            tension: 0.35,
            pointRadius: 5,
            pointHoverRadius: 7,
            pointBackgroundColor: lineColor,
            pointBorderColor: isDark ? '#0f172a' : '#ffffff',
            pointBorderWidth: 2
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: function(context) {
                  var rawVal = context.raw || 0;
                  return ' ₹' + rawVal.toLocaleString('en-IN', { minimumFractionDigits: 2 });
                }
              }
            }
          },
          scales: {
            x: {
              grid: { display: false },
              ticks: { color: textMuted, font: { family: 'Inter', weight: 500 } }
            },
            y: {
              grid: { color: gridColor },
              ticks: {
                color: textMuted,
                font: { family: 'Inter' },
                callback: function(val) {
                  if (val >= 1000) return '₹' + (val / 1000).toFixed(0) + 'k';
                  return '₹' + val;
                }
              }
            }
          }
        }
      });
    }

    // 2. Expenses by Category Horizontal Bar Chart
    var categoriesCanvas = document.getElementById('categoriesChart');
    if (categoriesCanvas) {
      var existing = Chart.getChart(categoriesCanvas);
      if (existing) existing.destroy();

      // Determine active tab for dynamic data loading
      var activeTab = 'expenses';
      if (document.getElementById('card-credits') && document.getElementById('card-credits').classList.contains('active')) {
        activeTab = 'credits';
      } else if (document.getElementById('card-debits') && document.getElementById('card-debits').classList.contains('active')) {
        activeTab = 'debits';
      }

      var catLabels = JSON.parse(categoriesCanvas.getAttribute('data-labels-' + activeTab) || '[]');
      var catValues = JSON.parse(categoriesCanvas.getAttribute('data-values-' + activeTab) || '[]');
      
      // Determine chart bar color based on tab
      var barColor = activeTab === 'credits' ? successColor : errorColor;
      if (activeTab === 'expenses') barColor = accentColor; // or keep errorColor

      var catHeight = Math.max(220, catLabels.length * 36) + 'px';
      categoriesCanvas.parentElement.style.height = catHeight;
      categoriesCanvas.parentElement.style.minHeight = catHeight;

      new Chart(categoriesCanvas, {
        type: 'bar',
        data: {
          labels: catLabels,
          datasets: [{
            data: catValues,
            backgroundColor: barColor,
            borderRadius: 6,
            barThickness: 16
          }]
        },
        options: {
          indexAxis: 'y',
          responsive: true,
          maintainAspectRatio: false,
          layout: {
            padding: {
              right: 90
            }
          },
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: function(context) {
                  var rawVal = context.raw || 0;
                  return ' ₹' + rawVal.toLocaleString('en-IN', { minimumFractionDigits: 2 });
                }
              }
            }
          },
          scales: {
            x: {
              grid: { color: gridColor },
              ticks: { color: textMuted, font: { family: 'Inter' } }
            },
            y: {
              grid: { display: false },
              ticks: {
                autoSkip: false,
                color: textMuted,
                font: { family: 'Inter', weight: 500 }
              }
            }
          }
        },
        plugins: [inlineDataLabels]
      });
    }

    // 3. Top Merchants Horizontal Bar Chart (Y Axis: Merchants, X Axis: Spent amount)
    var merchantsCanvas = document.getElementById('merchantsChart');
    if (merchantsCanvas) {
      var existing = Chart.getChart(merchantsCanvas);
      if (existing) existing.destroy();

      var merchLabels = JSON.parse(merchantsCanvas.getAttribute('data-labels-' + activeTab) || '[]');
      var merchValues = JSON.parse(merchantsCanvas.getAttribute('data-values-' + activeTab) || '[]');

      var merchHeight = Math.max(260, merchLabels.length * 36) + 'px';
      merchantsCanvas.parentElement.style.height = merchHeight;
      merchantsCanvas.parentElement.style.minHeight = merchHeight;

      new Chart(merchantsCanvas, {
        type: 'bar',
        data: {
          labels: merchLabels,
          datasets: [{
            data: merchValues,
            backgroundColor: isDark ? 'rgba(99, 102, 241, 0.85)' : 'rgba(79, 70, 229, 0.85)',
            hoverBackgroundColor: accentColor,
            borderRadius: 6,
            barThickness: 16
          }]
        },
        options: {
          indexAxis: 'y',
          responsive: true,
          maintainAspectRatio: false,
          layout: {
            padding: {
              right: 90
            }
          },
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: function(context) {
                  var rawVal = context.raw || 0;
                  return ' ₹' + rawVal.toLocaleString('en-IN', { minimumFractionDigits: 2 });
                }
              }
            }
          },
          scales: {
            x: {
              grid: { color: gridColor },
              ticks: { color: textMuted, font: { family: 'Inter' } }
            },
            y: {
              grid: { display: false },
              ticks: {
                autoSkip: false,
                color: textMuted,
                font: { family: 'Inter', weight: 500 }
              }
            }
          }
        },
        plugins: [inlineDataLabels]
      });
    }
  }

  // Initial render try
  try {
    if (typeof Chart !== 'undefined') {
      renderCharts();
    }
  } catch (err) {
    console.error("Initial chart render failed:", err);
  }

  // Window load try
  window.addEventListener('load', function () {
    try {
      if (typeof Chart !== 'undefined') {
        renderCharts();
      }
    } catch (err) {
      console.error("Window load chart render failed:", err);
    }
  });

  /* ── Form submit handlers: always preserve active tab and filters ── */
  document.querySelectorAll('form').forEach(function (form) {
    form.addEventListener('submit', function () {
      var activeTab = document.querySelector('.tab-link.active');
      if (activeTab) {
        sessionStorage.setItem('_active_tab', activeTab.getAttribute('data-tab'));
      }
      
      var params = new URLSearchParams(location.search);
      var filters = {};
      FILTER_KEYS.forEach(function (key) {
        if (params.has(key)) filters[key] = params.get(key);
      });

      // For POST requests, store filter queries to restore after redirect
      if (form.method.toLowerCase() === 'post') {
        sessionStorage.setItem('_ef', JSON.stringify(filters));
      } 
      // For GET requests, inject missing filters as hidden inputs so they aren't lost
      else if (form.method.toLowerCase() === 'get') {
        Object.keys(filters).forEach(function(key) {
          if (!form.querySelector('input[name="' + key + '"]')) {
            var hidden = document.createElement('input');
            hidden.type = 'hidden';
            hidden.name = key;
            hidden.value = filters[key];
            form.appendChild(hidden);
          }
        });
      }
    });
  });

  /* ── After a redirect: restore filter parameters ── */
  var params = new URLSearchParams(location.search);
  var isRedirect = params.has('message') || params.has('error');

  if (isRedirect) {
    var raw = sessionStorage.getItem('_ef');
    var targetTab = sessionStorage.getItem('_active_tab');
    sessionStorage.removeItem('_ef');

    if (raw) {
      var filters = JSON.parse(raw);
      var changed = false;
      Object.keys(filters).forEach(function (key) {
        if (!params.has(key)) {
          params.set(key, filters[key]);
          changed = true;
        }
      });
      if (changed) {
        var hash = targetTab ? '#' + targetTab : '';
        location.replace('?' + params.toString() + hash);
      }
    }
  }

  // Dynamic manual linker amount pre-population
  var manualDebit = document.getElementById('manual-debit-select');
  var manualCredit = document.getElementById('manual-credit-select');
  var manualAmount = document.getElementById('manual-link-amount');
  
  function updateManualLinkAmount() {
    if (manualDebit && manualCredit && manualAmount) {
      var dOpt = manualDebit.options[manualDebit.selectedIndex];
      var cOpt = manualCredit.options[manualCredit.selectedIndex];
      if (dOpt && cOpt && dOpt.value && cOpt.value) {
        var dRem = parseFloat(dOpt.getAttribute('data-remaining') || '0');
        var cRem = parseFloat(cOpt.getAttribute('data-remaining') || '0');
        manualAmount.value = Math.min(dRem, cRem).toFixed(2);
      }
    }
  }
  
  if (manualDebit) manualDebit.addEventListener('change', updateManualLinkAmount);
  if (manualCredit) manualCredit.addEventListener('change', updateManualLinkAmount);

  window.filterRulesTable = function() {
    var query = document.getElementById('rules-search-input').value.toLowerCase();
    var rows = document.querySelectorAll('#rules-table-body tr');
    rows.forEach(function(row) {
      if (row.classList.contains('empty-row')) return;
      var text = row.textContent.toLowerCase();
      row.style.display = text.includes(query) ? '' : 'none';
    });
  }

  /* ── Dashboard Metric Card Tab Switcher ── */
  window.switchDashboardTab = function (type) {
    // Update active classes on the 3 metric cards
    ['credits', 'debits', 'expenses'].forEach(function (t) {
      var card = document.getElementById('card-' + t);
      if (card) {
        if (t === type) {
          card.classList.add('active');
        } else {
          card.classList.remove('active');
        }
      }
    });

    // Update chart section headings based on selected card
    var trendTitle = document.getElementById('chart-trend-title');
    var categoryTitle = document.getElementById('chart-category-title');
    var merchantTitle = document.getElementById('chart-merchant-title');
    if (trendTitle) {
      if (type === 'credits') {
        trendTitle.innerText = 'Monthly credits trend';
      } else if (type === 'debits') {
        trendTitle.innerText = 'Monthly debits trend';
      } else {
        trendTitle.innerText = 'Monthly expense trend';
      }
    }
    if (categoryTitle && merchantTitle) {
      if (type === 'credits') {
        categoryTitle.innerText = 'Credits by category';
        merchantTitle.innerText = 'Top credit sources';
      } else if (type === 'debits') {
        categoryTitle.innerText = 'Debits by category';
        merchantTitle.innerText = 'Top merchants (Debits)';
      } else {
        categoryTitle.innerText = 'Expenses by category';
        merchantTitle.innerText = 'Top merchants';
      }
    }

    // Re-render charts to reflect active tab context
    if (typeof renderCharts === 'function') {
      renderCharts();
    }
  };

  window.selectExpenseType = function (chipBtn) {
    if (!chipBtn) return;
    var rowKey = chipBtn.getAttribute('data-row');
    var type = chipBtn.getAttribute('data-type');
    var selectEl = document.querySelector('select.expense-type-select[data-row="' + rowKey + '"]');
    if (selectEl) {
      selectEl.value = type;
    }
    var row = document.querySelector('.type-chip-row[data-row="' + rowKey + '"]');
    if (row) {
      row.querySelectorAll('.type-chip').forEach(function (c) {
        c.classList.toggle('active', c.getAttribute('data-type') === type);
      });
    }
    if (selectEl) {
      window.toggleTypeFields(selectEl);
    } else {
      var showShared = type === 'Shared';
      document.querySelectorAll('.shared-only-field[data-row="' + rowKey + '"]').forEach(function (el) {
        el.style.display = showShared ? '' : 'none';
        if (showShared) {
          var inputEl = el.querySelector('input[type="number"]');
          if (inputEl && (!inputEl.value || inputEl.value === '1' || inputEl.value === '0')) {
            inputEl.value = '2';
          }
        }
      });
    }
    window.updateStickyBatchCounts();
  };

  window.toggleTypeFields = function (selectEl) {
    if (!selectEl) return;
    var rowKey = selectEl.getAttribute('data-row');
    var type = selectEl.value;
    var showShared = type === 'Shared';
    document.querySelectorAll('.shared-only-field[data-row="' + rowKey + '"]').forEach(function (el) {
      el.style.display = showShared ? '' : 'none';
      if (showShared) {
        var inputEl = el.querySelector('input[type="number"]');
        if (inputEl && (!inputEl.value || inputEl.value === '1' || inputEl.value === '0')) {
          inputEl.value = '2';
        }
      }
    });
    // Keep chip UI in sync if select changed programmatically
    var row = document.querySelector('.type-chip-row[data-row="' + rowKey + '"]');
    if (row) {
      row.querySelectorAll('.type-chip').forEach(function (c) {
        c.classList.toggle('active', c.getAttribute('data-type') === type);
      });
    }
  };

  // Back-compat alias
  window.toggleSharedFields = window.toggleTypeFields;

  window.updateStickyBatchCounts = function () {
    document.querySelectorAll('form.review-batch-form').forEach(function (form) {
      var bar = form.querySelector('[data-sticky-bar]');
      if (!bar) return;
      var countEl = bar.querySelector('.sticky-count');
      var ready = 0;
      form.querySelectorAll('select.category-select, select[name^="category_"], select[name^="edit_category_"]').forEach(function (sel) {
        if (sel.value && sel.value.trim()) ready += 1;
      });
      if (countEl) countEl.textContent = String(ready);
      bar.classList.toggle('has-ready', ready > 0);
    });
  };

  // Init type fields + sticky counts on load
  document.querySelectorAll('select.expense-type-select').forEach(function (sel) {
    window.toggleTypeFields(sel);
  });
  window.updateStickyBatchCounts();
  document.addEventListener('change', function (e) {
    if (e.target && (e.target.classList.contains('category-select') ||
        (e.target.name && (e.target.name.indexOf('category_') === 0 || e.target.name.indexOf('edit_category_') === 0)))) {
      window.updateStickyBatchCounts();
    }
  });

  // Home strip links that jump tabs without full reload
  document.querySelectorAll('[data-tab-jump]').forEach(function (el) {
    el.addEventListener('click', function (e) {
      var tabId = el.getAttribute('data-tab-jump');
      if (!tabId) return;
      e.preventDefault();
      if (history.pushState) {
        history.pushState(null, null, '#' + tabId);
      }
      var tab = document.querySelector('.tab-link[data-tab="' + tabId + '"]');
      if (tab) tab.click();
      else window.location.hash = tabId;
      syncMobileNav(tabId);
    });
  });

  function syncMobileNav(tabId) {
    document.querySelectorAll('.mobile-bottom-nav .mnav-item[data-tab]').forEach(function (a) {
      a.classList.toggle('active', a.getAttribute('data-tab') === tabId);
    });
  }

  // Highlight mobile nav when desktop tabs change
  var _origSwitch = null;
  document.querySelectorAll('.tab-link[data-tab]').forEach(function (tab) {
    tab.addEventListener('click', function () {
      syncMobileNav(tab.getAttribute('data-tab'));
    });
  });
  syncMobileNav(location.hash ? location.hash.slice(1) : 'dashboard');

  /* ── P3: Home NL settlement question ── */
  window.askSettlementQuestion = function (event) {
    if (event) event.preventDefault();
    var input = document.getElementById('home-nl-input');
    var out = document.getElementById('home-nl-answer');
    if (!input || !out) return false;
    var raw = (input.value || '').trim();
    if (!raw) return false;
    var cleaned = raw
      .replace(/how much (does|do)\s+/i, '')
      .replace(/\s+owe me\??/i, '')
      .replace(/\?/g, '')
      .trim() || raw;
    out.hidden = false;
    out.className = 'home-nl-answer';
    out.textContent = 'Thinking…';
    fetch('/api/settlement/by-name?q=' + encodeURIComponent(cleaned), {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' }
    })
      .then(function (res) { return res.json().then(function (data) { return { ok: res.ok, data: data }; }); })
      .then(function (result) {
        if (!result.ok) {
          out.className = 'home-nl-answer error';
          out.textContent = result.data.error || 'Could not find that person.';
          return;
        }
        out.className = 'home-nl-answer';
        out.textContent = result.data.answer || ('Net ₹' + (result.data.net || 0));
      })
      .catch(function () {
        out.className = 'home-nl-answer error';
        out.textContent = 'Request failed. Are you logged in?';
      });
    return false;
  };

  /* ── People (khata) UX ── */
  window._drawerContactId = null;
  window._drawerContactName = '';
  window._drawerSettleNet = 0;
  window._peopleStatusFilter = 'active';

  /* ── Event Delegation for Khata / People Controls ── */
  document.addEventListener('click', function (e) {
    var actionBtn = e.target.closest('[data-action]');
    if (!actionBtn) return;

    var action = actionBtn.getAttribute('data-action');
    var card = actionBtn.closest('.contact-card');

    var contactId = actionBtn.getAttribute('data-contact-id') || (card && card.getAttribute('data-contact-id'));
    var contactName = actionBtn.getAttribute('data-contact-name') || (card && card.getAttribute('data-contact-name'));

    if (action === 'open-drawer') {
      window.openLedgerDrawer(contactId, contactName);
    } else if (action === 'edit-contact') {
      var aliases = actionBtn.getAttribute('data-aliases') || (card && card.getAttribute('data-aliases-raw')) || (card && card.getAttribute('data-aliases')) || '';
      var notes = actionBtn.getAttribute('data-notes') || (card && card.getAttribute('data-notes')) || '';
      window.openEditContactModal(contactId, contactName, aliases, notes);
    } else if (action === 'add-ledger') {
      window.openAddLedgerModal(contactId, contactName);
    } else if (action === 'open-modal') {
      var modalId = actionBtn.getAttribute('data-modal-id');
      if (modalId) window.openPeopleModal(modalId);
    } else if (action === 'close-modal') {
      var closeModalId = actionBtn.getAttribute('data-modal-id');
      if (closeModalId) window.closePeopleModal(closeModalId);
    } else if (action === 'close-drawer') {
      window.closeLedgerDrawer();
    } else if (action === 'filter-status') {
      var filterVal = actionBtn.getAttribute('data-filter');
      window.filterPeopleStatus(filterVal, actionBtn);
    }
  });

  document.addEventListener('input', function (e) {
    if (e.target && (e.target.id === 'contact-search-input' || e.target.getAttribute('data-action') === 'search-contacts')) {
      window.filterPeopleList();
    }
  });

  window.openPeopleModal = function (id) {
    var el = document.getElementById(id);
    if (el) el.hidden = false;
  };

  window.closePeopleModal = function (id) {
    var el = document.getElementById(id);
    if (el) el.hidden = true;
  };

  window.openAddLedgerModal = function (contactId, contactName) {
    var idEl = document.getElementById('ledger-modal-contact-id');
    var nameEl = document.getElementById('ledger-modal-contact-name');
    var dateEl = document.getElementById('ledger-modal-date');
    if (idEl) idEl.value = contactId;
    if (nameEl) nameEl.textContent = contactName || '';
    if (dateEl) dateEl.value = new Date().toISOString().split('T')[0];
    openPeopleModal('modal-add-ledger');
  };

  window.openEditContactModal = function (contactId, contactName, aliases, notes) {
    var idEl = document.getElementById('edit-contact-id');
    var nameEl = document.getElementById('edit-contact-name');
    var aliasEl = document.getElementById('edit-contact-aliases');
    var notesEl = document.getElementById('edit-contact-notes');
    if (idEl) idEl.value = contactId;
    if (nameEl) {
      nameEl.value = contactName || '';
      try { nameEl.focus(); nameEl.select(); } catch (err) { /* ignore */ }
    }
    if (aliasEl) aliasEl.value = aliases || '';
    if (notesEl) notesEl.value = notes || '';
    openPeopleModal('modal-edit-contact');
  };

  window.closeLedgerDrawer = function () {
    var drawer = document.getElementById('ledger-drawer');
    var backdrop = document.getElementById('ledger-drawer-backdrop');
    if (drawer) drawer.hidden = true;
    if (backdrop) backdrop.hidden = true;
  };

  function peopleQueryMatch(row, query) {
    if (!query) return true;
    var name = row.getAttribute('data-name') || '';
    var aliases = row.getAttribute('data-aliases') || '';
    return name.indexOf(query) !== -1 || aliases.indexOf(query) !== -1;
  }

  function applyPeopleFilters() {
    var input = document.getElementById('contact-search-input');
    var query = input ? input.value.toLowerCase().trim() : '';
    var status = window._peopleStatusFilter || 'active';
    var rows = document.querySelectorAll('.people-row.contact-card');
    rows.forEach(function (row) {
      var rowStatus = row.getAttribute('data-status') || '';
      var quiet = row.getAttribute('data-quiet') === '1';
      var statusOk = true;
      if (status === 'active') statusOk = !quiet && rowStatus !== 'settled';
      else if (status === 'all') statusOk = true;
      else statusOk = rowStatus === status;
      var show = statusOk && peopleQueryMatch(row, query);
      row.style.display = show ? 'flex' : 'none';
    });
    // When searching everyone or "all", open quiet panel so settled rows are reachable
    var quietPanel = document.getElementById('people-quiet-panel');
    if (quietPanel && (query || status === 'all' || status === 'settled')) {
      quietPanel.open = true;
    }
  }

  window.filterPeopleList = function () {
    applyPeopleFilters();
  };

  // Backward-compatible names used by older markup
  window.filterContactCards = window.filterPeopleList;
  window.filterContactStatus = function (status, btn) {
    window.filterPeopleStatus(status, btn);
  };

  window.filterPeopleStatus = function (status, btn) {
    window._peopleStatusFilter = status || 'active';
    document.querySelectorAll('.people-filter').forEach(function (p) {
      p.classList.toggle('active', p === btn);
    });
    applyPeopleFilters();
  };

  window.confirmSettle = function () {
    var absNet = Math.abs(window._drawerSettleNet || 0);
    var inp = document.getElementById('drawer-settle-amount');
    var raw = inp && inp.value ? parseFloat(inp.value) : absNet;
    if (!absNet) {
      alert('Already settled (₹0).');
      return false;
    }
    if (raw > absNet + 0.001) {
      alert('Amount cannot exceed ₹' + absNet.toLocaleString('en-IN'));
      return false;
    }
    var label = (inp && inp.value) ? ('₹' + raw.toLocaleString('en-IN')) : 'the full balance';
    return confirm('Mark ' + label + ' as settled?');
  };

  function purposeLabel(purpose, isPt, isOpening) {
    if (isPt) return 'Rolling (pass-through)';
    if (isOpening || purpose === 'opening_balance') return 'Starting balance';
    if (!purpose) return 'Entry';
    return String(purpose).replace(/_/g, ' ');
  }

  window.openLedgerDrawer = function (contactId, contactName) {
    var drawer = document.getElementById('ledger-drawer');
    var backdrop = document.getElementById('ledger-drawer-backdrop');
    if (!drawer) return;
    window._drawerContactId = contactId;
    window._drawerContactName = contactName || '';
    if (backdrop) backdrop.hidden = false;
    drawer.hidden = false;
    document.getElementById('drawer-contact-name').textContent = contactName || 'History';
    document.getElementById('drawer-settle-contact-id').value = contactId;
    var settleAmt = document.getElementById('drawer-settle-amount');
    if (settleAmt) settleAmt.value = '';
    window._drawerSettleNet = 0;

    var addBtn = document.getElementById('drawer-add-money-btn');
    if (addBtn) {
      addBtn.onclick = function () {
        openAddLedgerModal(contactId, contactName);
      };
    }
    var listEl = document.getElementById('drawer-entries-list');
    var summaryEl = document.getElementById('drawer-balance-summary');
    listEl.innerHTML = '<p class="empty">Loading…</p>';
    summaryEl.innerHTML = '';

    fetch('/api/contacts/ledger?contact_id=' + contactId)
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data.error) {
          listEl.innerHTML = '<p class="empty error">' + data.error + '</p>';
          return;
        }

        var bal = data.balance || {};
        var contact = data.contact || {};
        var entries = Array.isArray(data.entries) ? data.entries : [];
        var net = (bal.net_balance != null ? bal.net_balance : bal.net) || 0;
        window._drawerSettleNet = net;

        var editBtn = document.getElementById('drawer-edit-btn');
        if (editBtn) {
          var displayName = contact.name || contactName || '';
          var aliasesList = contact.aliases || [];
          var aliasesStr = Array.isArray(aliasesList) ? aliasesList.join(', ') : String(aliasesList || '');
          var notesStr = contact.notes || '';
          editBtn.onclick = function () {
            openEditContactModal(contactId, displayName, aliasesStr, notesStr);
          };
        }
        if (settleAmt) {
          settleAmt.placeholder = Math.abs(net) > 0
            ? ('Full ₹' + Math.abs(net).toLocaleString('en-IN'))
            : 'Settled';
        }

        var cls = net > 0 ? 'pos' : net < 0 ? 'neg' : '';
        var statusText = net > 0
          ? ('Owes you <strong class="pos">₹' + Number(net).toLocaleString('en-IN') + '</strong>')
          : net < 0
            ? ('You owe <strong class="neg">₹' + Math.abs(net).toLocaleString('en-IN') + '</strong>')
            : '<strong>Settled · ₹0</strong>';
        summaryEl.innerHTML = statusText +
          '<br><span style="font-size:12px;color:var(--muted)">You paid ₹' +
          Number(bal.total_you_sent || 0).toLocaleString('en-IN') +
          ' · They paid ₹' +
          Number(bal.total_they_sent || 0).toLocaleString('en-IN') +
          '</span>';

        if (!entries.length) {
          listEl.innerHTML = '<p class="empty">No history yet. Tap + Money to add a loan or split.</p>';
          return;
        }

        // Newest first for easier scanning
        var sorted = entries.slice().reverse();
        var html = '';
        sorted.forEach(function (e) {
          var isYou = e.direction === 'you_sent' || e.entry_type === 'you_sent';
          var isPt = !!e.is_passthrough;
          var amtCls = isYou ? 'pos' : 'neg';
          var prefix = isYou ? '+' : '−';
          var label = purposeLabel(e.purpose, isPt, e.is_opening_balance);
          var note = e.notes ? (' · ' + e.notes) : '';
          var run = (e.running_balance != null && !isPt)
            ? ('Balance after: ₹' + Number(e.running_balance).toLocaleString('en-IN'))
            : (isPt ? 'Does not change balance' : '');
          html += '<div class="people-hist-row' + (isPt ? ' is-pt' : '') + '" data-direction="' + (isYou ? 'you_sent' : 'they_sent') + '">' +
            '<div class="people-hist-date">' + (e.entry_date || '') + '</div>' +
            '<div class="people-hist-desc"><strong>' + label + '</strong><span>' +
            (isYou ? 'You paid' : 'They paid') + note + '</span></div>' +
            '<div class="people-hist-amt ' + amtCls + '">' + prefix + '₹' +
            Number(e.amount || 0).toLocaleString('en-IN') + '</div>' +
            (run ? '<div class="people-hist-balance">' + run + '</div>' : '') +
            '</div>';
        });
        listEl.innerHTML = html;
      })
      .catch(function (err) {
        console.error('Error fetching ledger:', err);
        listEl.innerHTML = '<p class="empty error">Could not load history.</p>';
      });
  };

  // Close people modals on backdrop click
  document.querySelectorAll('.people-modal').forEach(function (modal) {
    modal.addEventListener('click', function (e) {
      if (e.target === modal) modal.hidden = true;
    });
  });

  function isPeopleOverlayOpen(el) {
    return !!(el && !el.hidden && el.style.display !== 'none');
  }

  /** Esc closes Money/New person first, then History — back to People list. */
  window.closePeopleOverlays = function () {
    var money = document.getElementById('modal-add-ledger');
    var contact = document.getElementById('modal-add-contact');
    var drawer = document.getElementById('ledger-drawer');

    if (isPeopleOverlayOpen(money)) {
      closePeopleModal('modal-add-ledger');
      return true;
    }
    var edit = document.getElementById('modal-edit-contact');
    if (isPeopleOverlayOpen(edit)) {
      closePeopleModal('modal-edit-contact');
      return true;
    }
    if (isPeopleOverlayOpen(contact)) {
      closePeopleModal('modal-add-contact');
      return true;
    }
    if (isPeopleOverlayOpen(drawer)) {
      closeLedgerDrawer();
      return true;
    }
    return false;
  };

  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape' && e.key !== 'Esc') return;
    // Don't steal Esc from native dialogs / open <details> only — close our overlays
    if (window.closePeopleOverlays()) {
      e.preventDefault();
      e.stopPropagation();
    }
  });
})();
