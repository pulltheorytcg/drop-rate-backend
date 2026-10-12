from pathlib import Path
p=Path('backend/app/static/owner-imports.js');s=p.read_text()
def change(old,new):
 global s
 assert s.count(old)==1,(s.count(old),old[:100]);s=s.replace(old,new)
change('    dialog: null, generation: 0, busy: false, batch: null,','    dialog: null, generation: 0, historyRevision: 0, busy: false, batch: null,')
change('  function setBusy(active) {','''  function current(generation, batchId = null) {
    return generation === state.generation && Boolean(state.dialog?.open)
      && (batchId === null || state.batch?.id === batchId);
  }

  function setBusy(active) {''')
change('    if ($("owner-import-file")) $("owner-import-file").disabled = state.busy;','''    for (const id of ["owner-import-file", "owner-import-adapter", "owner-import-game", "owner-import-language"]) {
      if ($(id)) $(id).disabled = state.busy;
    }''')
change('''    resetPreview();
    if (state.dialog?.open) state.dialog.close();''','''    resetPreview();
    setBusy(false);
    $("owner-import-history-list")?.replaceChildren();
    message("");
    if (state.dialog?.open) state.dialog.close();''')
change('''    resetPreview();
    message("Upload your collection:''','''    resetPreview();
    setBusy(false);
    message("Upload your collection:''')
change('''  async function inspectFile() {
    state.fileContents''','''  async function inspectFile() {
    if (state.busy) return;
    state.generation++;
    state.fileContents''')
change('''    } catch (_error) {
      message("Could not read this CSV/TSV file.''','''    } catch (_error) {
      if (!current(generation) || file !== $("owner-import-file").files?.[0]) return;
      message("Could not read this CSV/TSV file.''')
change('''  async function updateCandidate(result) {
    if (!state.batch || state.batch.id !== String(result.batch_id)) return;
    const generation = state.generation;''','''  async function updateCandidate(result, generation) {
    if (!current(generation, String(result.batch_id))) return false;''')
change('''    if (generation !== state.generation || !state.dialog?.open) return;
    loadPreview(stored, result);
    await refreshInventory();
  }''','''    if (!current(generation, String(result.batch_id))) return false;
    loadPreview(stored, result);
    await refreshInventory();
    return current(generation, String(result.batch_id));
  }''')
change('    if (!state.batch || !window.confirm(`Skip source row','    if (state.busy || !state.batch || !window.confirm(`Skip source row')
s=s.replace('''    const batchId = state.batch.id;
    button.disabled = true;''','''    const batchId = state.batch.id, generation = state.generation;
    button.disabled = true;
    setBusy(true);''')
change('''      if (!state.batch || state.batch.id !== batchId || !state.dialog?.open) return;
      await updateCandidate(result);
      message(`Source row''','''      if (!current(generation, batchId) || !await updateCandidate(result, generation)) return;
      message(`Source row''')
change('''    } catch (_error) {
      message("This row could not be skipped. Refresh the import preview and retry.", "error");
      button.disabled = false;
    }''','''    } catch (_error) {
      if (!current(generation, batchId)) return;
      message("This row could not be skipped. Refresh the import preview and retry.", "error");
    } finally {
      if (current(generation, batchId)) { setBusy(false); button.disabled = false; }
    }''')
change('''    const runSearch = async () => {
      const term = input.value.trim();''','''    const generation = state.generation, batchId = state.batch?.id;
    let searchRevision = 0;
    const runSearch = async () => {
      const revision = ++searchRevision;
      const term = input.value.trim();
      const relevant = () => current(generation, batchId) && section.isConnected
        && revision === searchRevision && input.value.trim() === term;
      if (!relevant()) return;''')
change('''        const data = await apiRequest(`/api/v1/owner/imports/catalogue-search?${url.toString()}`);
        results.replaceChildren();''','''        const data = await apiRequest(`/api/v1/owner/imports/catalogue-search?${url.toString()}`);
        if (!relevant()) return;
        results.replaceChildren();''')
change('''      } catch (_error) {
        results.replaceChildren(node("small", "Catalogue search unavailable. Try again."));
      } finally {
        search.disabled = false;
      }''','''      } catch (_error) {
        if (relevant()) results.replaceChildren(node("small", "Catalogue search unavailable. Try again."));
      } finally {
        if (current(generation, batchId) && revision === searchRevision) search.disabled = false;
      }''')
change('''    if (!state.batch) return;
    const batchId = state.batch.id, generation''','''    if (state.busy || !state.batch) return;
    const batchId = state.batch.id, generation''')
change('''      if (!state.batch || state.batch.id !== batchId || !state.dialog?.open) return;
      await updateCandidate(result);
      message(result.candidate''','''      if (!current(generation, batchId) || !await updateCandidate(result, generation)) return;
      message(result.candidate''')
change('''    } catch (_error) {
      message("Confirmation could not finish. Refresh the import to check its current result before retrying.", "error");
      button.disabled = false;
    }''','''    } catch (_error) {
      if (!current(generation, batchId)) return;
      message("Confirmation could not finish. Refresh the import to check its current result before retrying.", "error");
    } finally {
      if (current(generation, batchId)) { setBusy(false); button.disabled = false; }
    }''')
change('''    const batchId = state.batch.id;
    setBusy(true);''','''    const batchId = state.batch.id, generation = state.generation;
    setBusy(true);''')
s=s.replace('      if (!state.batch || state.batch.id !== batchId || !state.dialog?.open) return;','      if (!current(generation, batchId)) return;')
change('''      await loadHistory();
      // Account-level inventory''','''      await loadHistory();
      if (!current(generation, batchId)) return;
      // Account-level inventory''')
change('''    } catch (_error) {
      message("Import could not finish. Refresh this batch to check which copies were already added before retrying.", "error");
    } finally {
      setBusy(false);
    }''','''    } catch (_error) {
      if (current(generation, batchId)) message("Import could not finish. Refresh this batch to check which copies were already added before retrying.", "error");
    } finally {
      if (current(generation, batchId)) setBusy(false);
    }''')
change('''    const generation = state.generation;
    const list = $("owner-import-history-list");''','''    const generation = state.generation, revision = ++state.historyRevision;
    const list = $("owner-import-history-list");''')
change('''      const data = await apiRequest("/api/v1/owner/imports?limit=8");
      if (generation !== state.generation || !state.dialog?.open) return;''','''      const data = await apiRequest("/api/v1/owner/imports?limit=8");
      if (!current(generation) || revision !== state.historyRevision) return;''')
change('''          resume.addEventListener("click", async () => {
            resume.disabled = true;''','''          resume.addEventListener("click", async () => {
            if (state.busy) return;
            const generation = ++state.generation;
            setBusy(true);
            resume.disabled = true;''')
change('''              if (!state.dialog?.open) return;
              loadPreview(stored);''','''              if (!current(generation)) return;
              loadPreview(stored);''')
change('''            } catch (_error) {
              message("Could not resume this import. Refresh and try again.", "error");
            } finally {
              resume.disabled = false;
            }''','''            } catch (_error) {
              if (current(generation)) message("Could not resume this import. Refresh and try again.", "error");
            } finally {
              if (current(generation)) { setBusy(false); resume.disabled = false; }
            }''')
change('''      if (generation === state.generation) {
        list.replaceChildren''','''      if (current(generation) && revision === state.historyRevision) {
        list.replaceChildren''')
change('  document.addEventListener("owner-view-changed",','''  window.addEventListener("hub-session-cleared", () => { hideMenu(); closeDialog(); });
  document.addEventListener("owner-view-changed",''')
p.write_text(s)
