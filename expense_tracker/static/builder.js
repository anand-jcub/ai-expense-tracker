(function () {
  'use strict';

  var unlinkedTxns = [];
  var activeCases = [];
  var suggestedLinks = [];

  // HTML references
  var builderTab = document.querySelector('.tab-link[data-tab="builder"]');
  var poolEl = document.getElementById('builder-pool');
  var casesGridEl = document.getElementById('builder-cases-grid');
  var unlinkedCountTag = document.getElementById('unlinked-count-tag');
  var searchInput = document.getElementById('builder-search');

  // Drag-and-drop state
  var draggedTxnId = null;

  // Initialize and register tab click trigger
  if (builderTab) {
    builderTab.addEventListener('click', initBuilder);
  }

  // Handle relationship sub-tab switching
  document.querySelectorAll('.sub-tab-link').forEach(function(link) {
    link.addEventListener('click', function() {
      var subtabId = link.getAttribute('data-subtab');
      
      // Toggle active link class
      document.querySelectorAll('.sub-tab-link').forEach(function(l) {
        l.classList.remove('active');
      });
      link.classList.add('active');

      // Toggle visible sub-pane
      document.querySelectorAll('.subtab-pane').forEach(function(pane) {
        if (pane.id === 'subpane-' + subtabId) {
          pane.style.display = 'block';
        } else {
          pane.style.display = 'none';
        }
      });
      
      // If switching to builder workspace, reload data
      if (subtabId === 'rel-builder') {
        loadBuilderData();
      }
    });
  });

  // Restore on page load if active tab is builder
  window.addEventListener('load', function() {
    if (sessionStorage.getItem('_active_tab') === 'builder') {
      initBuilder();
    }
  });

  // Handle SPA hash change
  window.addEventListener('hashchange', function() {
    if (location.hash === '#builder') {
      initBuilder();
    }
  });

  function initBuilder() {
    loadBuilderData();
  }

  function renderSkeletons() {
    var poolCreditsEl = document.getElementById('builder-pool-credits');
    var poolDebitsEl = document.getElementById('builder-pool-debits');
    var skeletonCard = 
      '<div class="skeleton-card" style="height:62px; background:var(--panel-hover); border:1px solid var(--line); border-radius:10px; margin-bottom:10px; position:relative; overflow:hidden;">' +
        '<div class="skeleton-shimmer" style="position:absolute; top:0; left:0; width:100%; height:100%; background:linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent); animation:shimmer 1.5s infinite;"></div>' +
      '</div>';
    
    if (poolCreditsEl) poolCreditsEl.innerHTML = skeletonCard + skeletonCard + skeletonCard;
    if (poolDebitsEl) poolDebitsEl.innerHTML = skeletonCard + skeletonCard + skeletonCard;
    if (casesGridEl) {
      casesGridEl.innerHTML = 
        '<div class="skeleton-card" style="height:180px; background:var(--panel-hover); border:1px solid var(--line); border-radius:14px; position:relative; overflow:hidden;">' +
          '<div class="skeleton-shimmer" style="position:absolute; top:0; left:0; width:100%; height:100%; background:linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent); animation:shimmer 1.5s infinite;"></div>' +
        '</div>' +
        '<div class="skeleton-card" style="height:180px; background:var(--panel-hover); border:1px solid var(--line); border-radius:14px; position:relative; overflow:hidden;">' +
          '<div class="skeleton-shimmer" style="position:absolute; top:0; left:0; width:100%; height:100%; background:linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent); animation:shimmer 1.5s infinite;"></div>' +
        '</div>';
    }
  }

  function loadBuilderData() {
    renderSkeletons();
    
    // Fetch transactions and suggestions concurrently
    Promise.all([
      fetch('/api/transactions').then(function(res) { return res.json(); }),
      fetch('/api/suggestions').then(function(res) { return res.json(); })
    ]).then(function(results) {
      var txData = results[0];
      suggestedLinks = results[1] || [];
 
      // Categorize transactions
      var allTxns = txData.transactions || [];
      activeCases = txData.active_relationships || [];
 
      // An unlinked transaction has active_relationship_id = null
      unlinkedTxns = allTxns.filter(function(t) {
        return !t.active_relationship_id;
      });
 
      renderPool(unlinkedTxns);
      renderCases(activeCases);
    }).catch(function(err) {
      console.error("Failed to load builder data:", err);
      if (poolEl) poolEl.innerHTML = '<p class="empty" style="color:var(--error); text-align:center; padding:20px;">Failed to load data</p>';
    });
  }

  // Render pool of unlinked cards
  function renderPool(txns) {
    var poolCreditsEl = document.getElementById('builder-pool-credits');
    var poolDebitsEl = document.getElementById('builder-pool-debits');
    if (!poolCreditsEl || !poolDebitsEl) return;

    poolCreditsEl.innerHTML = '';
    poolDebitsEl.innerHTML = '';
    
    var query = searchInput ? searchInput.value.toLowerCase().trim() : '';
    var filtered = txns.filter(function(t) {
      if (!query) return true;
      var amt = parseFloat(t.debit > 0 ? t.debit : t.credit).toFixed(2);
      return t.merchant_display.toLowerCase().includes(query) ||
             (t.description || '').toLowerCase().includes(query) ||
             (t.category || '').toLowerCase().includes(query) ||
             amt.includes(query);
    });

    if (unlinkedCountTag) unlinkedCountTag.textContent = filtered.length;

    var creditsCount = 0;
    var debitsCount = 0;

    filtered.forEach(function(t) {
      var isDebit = parseFloat(t.debit || 0) > 0;
      var amount = isDebit ? t.debit : t.credit;
      var amtClass = isDebit ? 'debit' : 'credit';
      var directionSymbol = isDebit ? '−' : '+';
      var cardId = 'txn-' + t.id;

      var card = document.createElement('div');
      card.id = cardId;
      card.className = 'txn-card ' + amtClass;
      card.setAttribute('draggable', 'true');
      card.style.cssText = 'background:var(--bg); border:1px solid var(--line); border-radius:10px; padding:10px 12px; cursor:grab; position:relative; user-select:none; display:flex; flex-direction:column; gap:4px; transition:border-color 0.2s, box-shadow 0.2s; margin-bottom:8px; overflow:hidden;';

      // Event listeners for dragging
      card.addEventListener('dragstart', function(e) {
        draggedTxnId = t.id;
        e.dataTransfer.setData('text/plain', t.id);
        card.style.opacity = '0.4';
        highlightValidTargets(t);
        
        // Highlight active containers as dropzones
        var containers = document.querySelectorAll('.case-container');
        containers.forEach(function(c) {
          c.classList.add('drop-target-active');
        });
      });

      card.addEventListener('dragend', function() {
        card.style.opacity = '1';
        clearHighlights();
        
        // Clear active dropzone styles
        var containers = document.querySelectorAll('.case-container');
        containers.forEach(function(c) {
          c.classList.remove('drop-target-active');
        });
      });

      // HTML5 drop zone setup (dropping one card onto another)
      card.addEventListener('dragover', function(e) {
        if (draggedTxnId && draggedTxnId !== t.id) {
          e.preventDefault();
          card.style.borderColor = 'var(--accent)';
          card.style.boxShadow = '0 0 8px var(--accent)';
        }
      });

      card.addEventListener('dragleave', function() {
        card.style.borderColor = 'var(--line)';
        card.style.boxShadow = 'none';
      });

      card.addEventListener('drop', function(e) {
        e.preventDefault();
        card.style.borderColor = 'var(--line)';
        card.style.boxShadow = 'none';
        
        var sourceId = parseInt(e.dataTransfer.getData('text/plain'), 10);
        if (sourceId && sourceId !== t.id) {
          openBuilderRelationshipModal(sourceId, t.id);
        }
      });

      card.innerHTML = 
        '<div style="display:flex; justify-content:space-between; align-items:flex-start; gap:6px; min-width:0; overflow:hidden;">' +
          '<strong class="text-truncate" style="font-size:12px; color:var(--ink); flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">' + esc(t.merchant_display) + '</strong>' +
          '<span class="amount ' + amtClass + '" style="font-weight:700; font-size:12px; white-space:nowrap; flex-shrink:0;">' + directionSymbol + ' ₹' + parseFloat(amount).toFixed(2) + '</span>' +
        '</div>' +
        '<div style="display:flex; justify-content:space-between; align-items:center; font-size:11px; color:var(--muted); margin-top:2px;">' +
          '<span>' + t.txn_date + '</span>' +
          '<span class="tag" style="background:var(--panel-hover); padding:1px 6px; border-radius:4px; font-size:9px; font-weight:600;">' + esc(t.category || 'Unclassified') + '</span>' +
        '</div>';

      if (isDebit) {
        poolDebitsEl.appendChild(card);
        debitsCount++;
      } else {
        poolCreditsEl.appendChild(card);
        creditsCount++;
      }
    });

    if (creditsCount === 0) {
      poolCreditsEl.innerHTML = '<p class="empty" style="text-align:center; padding:20px; color:var(--muted); font-size:11px;">No credits</p>';
    }
    if (debitsCount === 0) {
      poolDebitsEl.innerHTML = '<p class="empty" style="text-align:center; padding:20px; color:var(--muted); font-size:11px;">No debits</p>';
    }
    
    var creditsTag = document.getElementById('credits-count-tag');
    var debitsTag = document.getElementById('debits-count-tag');
    if (creditsTag) creditsTag.textContent = creditsCount;
    if (debitsTag) debitsTag.textContent = debitsCount;
  }

  // Filter pool function exposed globally
  window.filterBuilderPool = function() {
    renderPool(unlinkedTxns);
  };

  // Render list of active cases as drop containers
  function renderCases(cases) {
    if (!casesGridEl) return;
    casesGridEl.innerHTML = '';

    if (cases.length === 0) {
      casesGridEl.innerHTML = 
        '<div class="empty-state-card" style="grid-column:1/-1; display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; padding:40px 20px; background:var(--panel); border:2px dashed var(--line); border-radius:14px; min-height:220px; color:var(--muted);">' +
          '<svg style="width:48px; height:48px; fill:var(--muted); margin-bottom:12px;" viewBox="0 0 24 24">' +
            '<path d="M19 15v4H5v-4h14m1-2H4c-.55 0-1 .45-1 1v6c0 .55.45 1 1 1h16c.55 0 1-.45 1-1v-6c0-.55-.45-1-1-1zm-6-8.5c.83 0 1.5-.67 1.5-1.5S13.83 1 13 1s-1.5.67-1.5 1.5.67 1.5 1.5 1.5zm3.5 3.5c.83 0 1.5-.67 1.5-1.5S17.33 5 16.5 5 15 5.67 15 6.5s.67 1.5 1.5 1.5zm-7 0C10.33 8 11 7.33 11 6.5S10.33 5 9.5 5 8 5.67 8 6.5 8.67 8 9.5 8z"/>' +
          '</svg>' +
          '<strong style="color:var(--ink); font-size:14px; margin-bottom:6px;">No Active Cases Yet</strong>' +
          '<p style="font-size:12px; margin:0 0 16px 0; max-width:320px; line-height:1.4;">Start by linking two unlinked transactions or click below to spawn a new empty Case container.</p>' +
          '<button type="button" class="button btn-approve small" onclick="openNewCaseModal()" style="border-radius:8px; padding:6px 14px; font-weight:600; font-size:11px;">+ Initialize Case</button>' +
        '</div>';
      return;
    }

    cases.forEach(function(c) {
      var relType = c.relationship_type;
      var style = getCaseStyle(relType);

      var container = document.createElement('div');
      container.className = 'case-container';
      
      // Calculate totals
      var debitSum = 0;
      var creditSum = 0;
      c.members.forEach(function(m) {
        var amt = parseFloat(m.amount || 0);
        if (parseFloat(m.debit || 0) > 0) debitSum += amt;
        else creditSum += amt;
      });
      var totalCaseVal = Math.max(debitSum, creditSum);
      var diff = creditSum - debitSum;

      // Styling case container dynamically as a small square bucket card
      container.style.cssText = 'background:var(--panel); border:2px dashed var(--line); border-left:4px solid ' + style.color + ' !important; border-radius:10px; padding:8px; width:120px; height:80px; display:flex; flex-direction:column; justify-content:space-between; align-items:center; transition:border-color 0.2s, background-color 0.2s, box-shadow 0.2s; position:relative;';

      // Drag over case event listeners
      container.addEventListener('dragover', function(e) {
        e.preventDefault();
        container.style.borderColor = style.color;
        container.style.backgroundColor = 'var(--panel-hover)';
        container.style.boxShadow = '0 0 10px ' + style.color + '44';
      });

      container.addEventListener('dragleave', function() {
        container.style.borderColor = 'var(--line)';
        container.style.backgroundColor = 'var(--panel)';
        container.style.boxShadow = 'none';
      });

      container.addEventListener('drop', function(e) {
        e.preventDefault();
        container.style.borderColor = 'var(--line)';
        container.style.backgroundColor = 'var(--panel)';
        container.style.boxShadow = 'none';

        var txnId = parseInt(e.dataTransfer.getData('text/plain'), 10);
        if (txnId) {
          addTransactionToCase(c.relationship_id, txnId);
        }
      });

      var caseName = c.notes ? esc(c.notes) : 'Unnamed Bucket #' + c.relationship_id;
      var memberCount = c.members.length;

      var itemsCountHtml = '<span class="tag" style="background:var(--panel-hover); color:var(--ink); font-weight:700; border-radius:4px; padding:1px 5px; font-size:9px; border:1px solid var(--line); margin-bottom: 2px;" title="Linked transactions">' + memberCount + ' txns</span>';

      container.innerHTML = 
        '<button type="button" onclick="deleteCase(' + c.relationship_id + ')" style="position:absolute; top:4px; right:6px; background:transparent; border:none; color:var(--error); font-size:13px; font-weight:bold; cursor:pointer; padding:0; line-height:1;" title="Delete bucket">×</button>' +
        '<span class="text-truncate" style="font-size:11px; font-weight:600; color:var(--ink); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; width:100%; text-align:center; margin-top:14px; padding:0 4px;" title="' + caseName + '">' + caseName + '</span>' +
        itemsCountHtml;

      casesGridEl.appendChild(container);
    });
  }

  // Get style configs for cases
  function getCaseStyle(type) {
    var styles = {
      "Refund": { bg: "hsla(142, 70%, 45%, 0.12)", color: "hsl(142, 75%, 38%)", icon: "↩️" },
      "Internal Transfer": { bg: "hsla(200, 80%, 50%, 0.12)", color: "hsl(200, 85%, 38%)", icon: "🔄" },
      "Loan Returned": { bg: "hsla(270, 75%, 50%, 0.12)", color: "hsl(270, 80%, 42%)", icon: "🤝" },
      "Temporary Fund Movement": { bg: "hsla(180, 75%, 45%, 0.12)", color: "hsl(180, 80%, 35%)", icon: "⏳" },
      "Shared Expense Settlement": { bg: "hsla(30, 90%, 50%, 0.12)", color: "hsl(30, 95%, 38%)", icon: "👥" },
      "Reimbursement": { bg: "hsla(300, 70%, 45%, 0.12)", color: "hsl(300, 75%, 38%)", icon: "💼" },
      "Cashback": { bg: "hsla(45, 95%, 50%, 0.12)", color: "hsl(40, 95%, 32%)", icon: "💰" },
      "Charge Reversal": { bg: "hsla(0, 80%, 50%, 0.12)", color: "hsl(0, 85%, 42%)", icon: "⚠️" }
    };
    return styles[type] || { bg: "var(--line)", color: "var(--ink)", icon: "🔗" };
  }

  // Highlight targets based on suggested matching links
  function highlightValidTargets(srcTxn) {
    var isDebit = parseFloat(srcTxn.debit || 0) > 0;
    
    // Find suggestions involving the source transaction
    var matchedDestIds = [];
    suggestedLinks.forEach(function(sug) {
      var memberIds = sug.members.map(function(m) { return m.transaction_id; });
      if (memberIds.includes(srcTxn.id)) {
        memberIds.forEach(function(id) {
          if (id !== srcTxn.id) matchedDestIds.push(id);
        });
      }
    });

    unlinkedTxns.forEach(function(t) {
      if (t.id === srcTxn.id) return;
      var card = document.getElementById('txn-' + t.id);
      if (!card) return;

      var targetIsDebit = parseFloat(t.debit || 0) > 0;
      var isOppositeDirection = (isDebit !== targetIsDebit);
      var isSuggested = matchedDestIds.includes(t.id);

      if (isSuggested) {
        card.style.borderColor = 'var(--success)';
        card.style.boxShadow = '0 0 6px var(--success-glow)';
      } else if (isOppositeDirection) {
        card.style.borderColor = 'var(--accent-glow)';
      } else {
        card.style.opacity = '0.3';
      }
    });
  }

  function clearHighlights() {
    unlinkedTxns.forEach(function(t) {
      var card = document.getElementById('txn-' + t.id);
      if (card) {
        card.style.borderColor = 'var(--line)';
        card.style.boxShadow = 'none';
        card.style.opacity = '1';
      }
    });
  }

  // Open creation modal for dragging Card to Card
  var cardAId = null;
  var cardBId = null;

  function openBuilderRelationshipModal(idA, idB) {
    cardAId = idA;
    cardBId = idB;

    var txA = unlinkedTxns.find(function(t) { return t.id === idA; });
    var txB = unlinkedTxns.find(function(t) { return t.id === idB; });
    if (!txA || !txB) return;

    var textAEl = document.getElementById('builder-rel-card-a-text');
    var textBEl = document.getElementById('builder-rel-card-b-text');
    var typeEl = document.getElementById('builder-rel-type');
    var notesEl = document.getElementById('builder-rel-notes');
    var modal = document.getElementById('builder-relationship-modal');

    if (textAEl && textBEl && modal) {
      textAEl.textContent = txA.merchant_display + ' (' + (txA.debit > 0 ? 'Debit' : 'Credit') + ' ₹' + parseFloat(txA.debit > 0 ? txA.debit : txA.credit).toFixed(2) + ')';
      textBEl.textContent = txB.merchant_display + ' (' + (txB.debit > 0 ? 'Debit' : 'Credit') + ' ₹' + parseFloat(txB.debit > 0 ? txB.debit : txB.credit).toFixed(2) + ')';
      
      // Auto-suggest type if we have suggestion logs
      var matchedType = "Custom";
      suggestedLinks.forEach(function(sug) {
        var memberIds = sug.members.map(function(m) { return m.transaction_id; });
        if (memberIds.includes(idA) && memberIds.includes(idB)) {
          matchedType = sug.relationship_type;
        }
      });
      if (typeEl) typeEl.value = matchedType;
      if (notesEl) notesEl.value = '';

      var amtEl = document.getElementById('builder-link-amount');
      if (amtEl) {
        var amtA = parseFloat(txA.debit > 0 ? txA.debit : txA.credit);
        var amtB = parseFloat(txB.debit > 0 ? txB.debit : txB.credit);
        amtEl.value = Math.min(amtA, amtB).toFixed(2);
      }

      modal.style.display = 'flex';
    }
  }

  window.closeBuilderRelModal = function() {
    var modal = document.getElementById('builder-relationship-modal');
    if (modal) modal.style.display = 'none';
  };

  // Submit relationship creation form via Ajax
  window.submitBuilderRel = function() {
    var typeEl = document.getElementById('builder-rel-type');
    var notesEl = document.getElementById('builder-rel-notes');
    if (!typeEl) return;

    var txA = unlinkedTxns.find(function(t) { return t.id === cardAId; });
    var txB = unlinkedTxns.find(function(t) { return t.id === cardBId; });
    if (!txA || !txB) return;

    var amtEl = document.getElementById('builder-link-amount');
    var targetAmt = amtEl ? parseFloat(amtEl.value) : Math.min(
      parseFloat(txA.debit > 0 ? txA.debit : txA.credit),
      parseFloat(txB.debit > 0 ? txB.debit : txB.credit)
    );

    var body = {
      relationship_type: typeEl.value,
      notes: notesEl ? notesEl.value : '',
      members: [
        { transaction_id: cardAId, role: txA.debit > 0 ? 'debit' : 'credit', amount: targetAmt },
        { transaction_id: cardBId, role: txB.debit > 0 ? 'debit' : 'credit', amount: targetAmt }
      ]
    };

    fetch('/relationship/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function(res) {
      if (!res.ok) throw new Error("HTTP error " + res.status);
      return res.json();
    }).then(function() {
      closeBuilderRelModal();
      showToast("Linked transactions successfully!", false);
      loadBuilderData();
    }).catch(function(err) {
      console.error(err);
      showToast("Link failed: " + err.message, true);
    });
  };

  // Drop transaction into an existing active Case dropzone
  function addTransactionToCase(caseId, txnId) {
    var body = {
      relationship_id: caseId,
      transaction_id: txnId
    };

    fetch('/relationship/add-member', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function(res) {
      if (!res.ok) throw new Error("HTTP error " + res.status);
      return res.json();
    }).then(function() {
      showToast("Added transaction to Case successfully!", false);
      loadBuilderData();
    }).catch(function(err) {
      console.error(err);
      showToast("Add failed: " + err.message, true);
    });
  }

  // Expand empty case modal
  window.openNewCaseModal = function() {
    var modal = document.getElementById('builder-new-case-modal');
    if (modal) {
      document.getElementById('builder-new-case-notes').value = '';
      modal.style.display = 'flex';
    }
  };

  window.closeNewCaseModal = function() {
    var modal = document.getElementById('builder-new-case-modal');
    if (modal) modal.style.display = 'none';
  };

  window.submitNewCase = function() {
    var typeEl = document.getElementById('builder-new-case-type');
    var notesEl = document.getElementById('builder-new-case-notes');
    if (!typeEl) return;

    var body = {
      relationship_type: typeEl.value,
      notes: notesEl ? notesEl.value : '',
      members: [] // creates empty active container
    };

    fetch('/relationship/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function(res) {
      if (!res.ok) throw new Error("HTTP error " + res.status);
      return res.json();
    }).then(function() {
      closeNewCaseModal();
      showToast("Created Financial Case container successfully!", false);
      loadBuilderData();
    }).catch(function(err) {
      console.error(err);
      showToast("Create case failed: " + err.message, true);
    });
  };

  window.removeTransactionFromCase = function(relationshipId, transactionId) {
    if (!confirm('Remove this transaction from this case?')) return;
    
    fetch('/relationship/remove-member', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ relationship_id: relationshipId, transaction_id: transactionId })
    })
    .then(function(res) {
      if (!res.ok) throw new Error("HTTP error " + res.status);
      return res.json();
    })
    .then(function(data) {
      if (data.success) {
        showToast("Transaction removed from case", false);
        loadBuilderData(); // Reload workspace
      } else {
        showToast("Error: " + data.error, true);
      }
    })
    .catch(function(err) {
      console.error("Error removing member:", err);
      showToast("Network error removing member: " + err.message, true);
    });
  };

  function removeSuggestionRowDOM(id) {
    var el = document.getElementById('sug-row-' + id);
    if (!el) return;
    el.style.transition = 'all 0.3s ease-out';
    el.style.opacity = '0';
    el.style.maxHeight = '0';
    el.style.paddingTop = '0';
    el.style.paddingBottom = '0';
    el.style.marginTop = '0';
    el.style.marginBottom = '0';
    el.style.overflow = 'hidden';
    setTimeout(function() {
      el.remove();
      
      var subtabBadge = document.getElementById('subtab-suggestions-count-tag');
      var pendingCount = document.getElementById('suggestions-pending-count');
      var sidebarBadge = document.getElementById('suggestions-badge');
      
      if (subtabBadge) {
        var count = parseInt(subtabBadge.textContent) - 1;
        if (count <= 0) subtabBadge.remove();
        else subtabBadge.textContent = count;
      }
      if (pendingCount) {
        var count = parseInt(pendingCount.textContent) - 1;
        pendingCount.textContent = count + ' pending suggestions';
      }
      if (sidebarBadge) {
        var count = parseInt(sidebarBadge.textContent) - 1;
        if (count <= 0) sidebarBadge.remove();
        else sidebarBadge.textContent = count;
      }
    }, 300);
  }

  window.approveSuggestion = function(id) {
    fetch('/relationship/approve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ relationship_id: id })
    })
    .then(function(res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then(function(data) {
      if (data.success) {
        removeSuggestionRowDOM(id);
        showToast("Approved suggestion successfully!", false);
        loadBuilderData();
      } else {
        showToast("Error: " + data.error, true);
      }
    })
    .catch(function(err) {
      console.error(err);
      showToast("Approve failed: " + err.message, true);
    });
  };

  window.rejectSuggestion = function(id) {
    fetch('/relationship/reject', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ relationship_id: id })
    })
    .then(function(res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then(function(data) {
      if (data.success) {
        removeSuggestionRowDOM(id);
        showToast("Suggestion rejected.", false);
        loadBuilderData();
      } else {
        showToast("Error: " + data.error, true);
      }
    })
    .catch(function(err) {
      console.error(err);
      showToast("Reject failed: " + err.message, true);
    });
  };

  window.ignoreSuggestion = function(id) {
    fetch('/relationship/ignore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ relationship_id: id })
    })
    .then(function(res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then(function(data) {
      if (data.success) {
        removeSuggestionRowDOM(id);
        showToast("Suggestion ignored.", false);
        loadBuilderData();
      } else {
        showToast("Error: " + data.error, true);
      }
    })
    .catch(function(err) {
      console.error(err);
      showToast("Ignore failed: " + err.message, true);
    });
  };

  window.bulkApproveSuggestions = function() {
    fetch('/api/suggestions')
    .then(function(res) { return res.json(); })
    .then(function(suggs) {
      var highConf = suggs.filter(function(s) {
        return parseFloat(s.confidence) >= 0.9;
      });
      if (highConf.length === 0) {
        showToast("No high confidence suggestions found.", true);
        return;
      }
      if (!confirm("Approve " + highConf.length + " high confidence suggestions?")) return;

      var promises = highConf.map(function(s) {
        return fetch('/relationship/approve', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ relationship_id: s.relationship_id })
        }).then(function(res) { return res.json(); });
      });

      Promise.all(promises)
      .then(function(results) {
        showToast("Successfully approved " + results.length + " suggestions!", false);
        highConf.forEach(function(s) {
          removeSuggestionRowDOM(s.relationship_id);
        });
        loadBuilderData();
      })
      .catch(function(err) {
        console.error(err);
        showToast("Bulk approve failed: " + err.message, true);
      });
    });
  };

  window.deleteCase = function(id) {
    if (!confirm('Delete this case? All connected transactions will be returned to the unlinked pool.')) return;
    fetch('/relationship/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ relationship_id: id })
    })
    .then(function(res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then(function(data) {
      if (data.success) {
        showToast("Case deleted successfully", false);
        loadBuilderData();
      } else {
        showToast("Error deleting case: " + data.error, true);
      }
    })
    .catch(function(err) {
      console.error(err);
      showToast("Delete case failed: " + err.message, true);
    });
  };

  window.deleteRelationshipRow = function(btn, id) {
    if (!confirm('Remove this relationship?')) return;
    fetch('/relationship/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ relationship_id: id })
    })
    .then(function(res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then(function(data) {
      if (data.success) {
        showToast("Relationship removed successfully", false);
        var row = btn.closest('tr');
        if (row) {
          row.style.transition = 'all 0.3s ease-out';
          row.style.opacity = '0';
          setTimeout(function() { row.remove(); }, 300);
        } else {
          location.reload();
        }
      } else {
        showToast("Error removing relationship: " + data.error, true);
      }
    })
    .catch(function(err) {
      console.error(err);
      showToast("Remove failed: " + err.message, true);
    });
  };

  // HTML escaping helper
  function esc(s) {
    if (!s) return '';
    return s.toString()
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Immediate check if script executes and page is ready
  var activeTab = sessionStorage.getItem('_active_tab');
  var isBuilderActive = builderTab && builderTab.classList.contains('active');
  if (location.hash === '#builder' || activeTab === 'builder' || isBuilderActive) {
    initBuilder();
  }

})();
