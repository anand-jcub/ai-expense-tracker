/* SPA Tab switching, Chart.js rendering, Theme Toggle, Scroll & Filter preservation */
(function () {
  'use strict';

  var FILTER_KEYS = [
    'start_date', 'end_date', 'exclude_business', 'use_my_share',
    'review_sort', 'review_search', 'edit_search', 'person_search'
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

    // Update URL hash without jumping/scrolling
    if (history.pushState) {
      history.pushState(null, null, '#' + tabId);
    } else {
      location.hash = '#' + tabId;
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
  if (initialTab === 'edit-classifications') initialTab = 'transactions';
  if (initialTab === 'merchant-rules' || initialTab === 'shared-expenses') initialTab = 'rules';
  switchTab(initialTab);

  // Sync tab switching on hash change
  window.addEventListener('hashchange', function () {
    var hash = location.hash.slice(1);
    if (hash === 'person-search') hash = 'search';
    if (hash === 'edit-classifications') hash = 'transactions';
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
              var formatted = 'Rs ' + value.toLocaleString('en-IN', { minimumFractionDigits: 2 });
              ctx.fillText(formatted, bar.x + 8, bar.y);
            }
          });
        });
        ctx.restore();
      }
    };

    // 1. Credit / Debit Donut Chart
    var donutCanvas = document.getElementById('creditDebitChart');
    if (donutCanvas) {
      var existing = Chart.getChart(donutCanvas);
      if (existing) existing.destroy();
      
      var creditVal = parseFloat(donutCanvas.getAttribute('data-credit') || '0');
      var debitVal = parseFloat(donutCanvas.getAttribute('data-debit') || '0');
      
      new Chart(donutCanvas, {
        type: 'doughnut',
        data: {
          labels: ['Credits', 'Debits'],
          datasets: [{
            data: [creditVal, debitVal],
            backgroundColor: [successColor, errorColor],
            borderWidth: 0,
            hoverOffset: 4
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
                  return ' ' + context.label + ': Rs ' + rawVal.toLocaleString('en-IN', { minimumFractionDigits: 2 });
                }
              }
            }
          },
          cutout: '72%'
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
                  return ' Rs ' + rawVal.toLocaleString('en-IN', { minimumFractionDigits: 2 });
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
                  return ' Rs ' + rawVal.toLocaleString('en-IN', { minimumFractionDigits: 2 });
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
    var categoryTitle = document.getElementById('chart-category-title');
    var merchantTitle = document.getElementById('chart-merchant-title');
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

  /* ── Contact Ledger Drawer & Modal JS ── */
  window.openAddLedgerModal = function (contactId, contactName) {
    document.getElementById('ledger-modal-contact-id').value = contactId;
    document.getElementById('ledger-modal-contact-name').innerText = contactName;
    document.getElementById('ledger-modal-date').value = new Date().toISOString().split('T')[0];
    document.getElementById('modal-add-ledger').style.display = 'flex';
  };

  window.closeLedgerDrawer = function () {
    var drawer = document.getElementById('ledger-drawer');
    if (drawer) drawer.style.display = 'none';
  };

  window.openLedgerDrawer = function (contactId, contactName) {
    var drawer = document.getElementById('ledger-drawer');
    if (!drawer) return;
    drawer.style.display = 'flex';
    document.getElementById('drawer-contact-name').innerText = contactName + ' - Ledger History';
    document.getElementById('drawer-settle-contact-id').value = contactId;

    var listEl = document.getElementById('drawer-entries-list');
    var summaryEl = document.getElementById('drawer-balance-summary');
    listEl.innerHTML = '<p class="empty">Loading ledger entries...</p>';
    summaryEl.innerHTML = '';

    fetch('/api/contacts/ledger?contact_id=' + contactId)
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data.error) {
          listEl.innerHTML = '<p class="empty error">' + data.error + '</p>';
          return;
        }

        var bal = data.balance || {};
        var net = bal.net_balance || 0;
        var statusText = net > 0 ? ('Owes you Rs ' + net.toLocaleString('en-IN')) :
          net < 0 ? ('You owe Rs ' + Math.abs(net).toLocaleString('en-IN')) : 'Settled (Rs 0)';

        summaryEl.innerHTML =
          '<div><strong>Net Status:</strong> <span style="font-weight:600;">' + statusText + '</span></div>' +
          '<div style="font-size:12px; color:var(--muted); margin-top:4px;">Total Sent: Rs ' + (bal.total_you_sent || 0).toLocaleString('en-IN') +
          ' | Total Received: Rs ' + (bal.total_they_sent || 0).toLocaleString('en-IN') + '</div>';

        var entries = data.entries || [];
        if (!entries.length) {
          listEl.innerHTML = '<p class="empty">No ledger entries yet.</p>';
          return;
        }

        var html = '<div style="display:flex; flex-direction:column; gap:10px;">';
        entries.forEach(function (e) {
          var isYou = e.entry_type === 'you_sent';
          var color = isYou ? 'var(--success)' : 'var(--error)';
          var prefix = isYou ? '+ ' : '- ';
          var passthroughBadge = e.is_passthrough ? '<span class="badge subtle" style="font-size:10px; margin-left:6px;">Pass-Through</span>' : '';
          var openingBadge = e.is_opening_balance ? '<span class="badge warn" style="font-size:10px; margin-left:6px;">Opening Balance</span>' : '';
          var noteText = e.notes ? ('<div style="font-size:12px; color:var(--muted); margin-top:2px;">' + e.notes + '</div>') : '';
          var purposeText = e.purpose ? ('<span class="badge subtle" style="font-size:10px;">' + e.purpose + '</span>') : '';

          html += '<div style="background:var(--background-color); border:1px solid var(--border-color); border-radius:6px; padding:10px;">' +
            '<div style="display:flex; justify-content:space-between; align-items:center;">' +
            '<span style="font-size:12px; color:var(--muted);">' + (e.entry_date || '') + '</span>' +
            '<strong style="color:' + color + ';">' + prefix + 'Rs ' + (e.amount || 0).toLocaleString('en-IN') + '</strong>' +
            '</div>' +
            '<div style="margin-top:4px;">' + purposeText + passthroughBadge + openingBadge + '</div>' +
            noteText +
            '</div>';
        });
        html += '</div>';
        listEl.innerHTML = html;
      })
      .catch(function (err) {
        console.error('Error fetching ledger:', err);
        listEl.innerHTML = '<p class="empty error">Failed to load ledger history.</p>';
      });
  };
})();
