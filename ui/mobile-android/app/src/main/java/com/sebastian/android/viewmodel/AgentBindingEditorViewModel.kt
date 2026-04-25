package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.AgentBinding
import com.sebastian.android.data.model.CatalogProvider
import com.sebastian.android.data.model.CustomModel
import com.sebastian.android.data.model.LlmAccount
import com.sebastian.android.data.model.ResolvedBinding
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.model.ThinkingEffort
import com.sebastian.android.data.model.toApiString
import com.sebastian.android.data.model.toThinkingEffort
import com.sebastian.android.data.repository.AgentRepository
import com.sebastian.android.data.repository.SettingsRepository
import com.sebastian.android.di.ApplicationScope
import com.sebastian.android.ui.settings.components.effortStepsFor
import dagger.assisted.Assisted
import dagger.assisted.AssistedFactory
import dagger.assisted.AssistedInject
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class EditorUiState(
    val agentType: String,
    val agentDisplayName: String = "",
    val isOrchestrator: Boolean = false,
    val isDefault: Boolean = false,
    val loading: Boolean = true,
    val accounts: List<LlmAccount> = emptyList(),
    val catalogProviders: List<CatalogProvider> = emptyList(),
    val selectedAccount: LlmAccount? = null,
    val availableModels: List<ModelOption> = emptyList(),
    val selectedModel: ModelOption? = null,
    val thinkingEffort: ThinkingEffort = ThinkingEffort.OFF,
    val resolved: ResolvedBinding? = null,
    val isSaving: Boolean = false,
    val errorMessage: String? = null,
) {
    val effectiveCapability: ThinkingCapability?
        get() = selectedModel?.thinkingCapability

    val contextWindowText: String?
        get() = selectedModel?.contextWindowTokens?.let { tokens ->
            if (tokens >= 1_000_000) {
                "${tokens / 1_000_000}M tokens"
            } else {
                "%,d tokens".format(tokens)
            }
        }
}

data class ModelOption(
    val id: String,
    val displayName: String,
    val contextWindowTokens: Long,
    val thinkingCapability: ThinkingCapability,
)

sealed interface EditorEvent {
    data class Snackbar(val text: String) : EditorEvent
}

@HiltViewModel(assistedFactory = AgentBindingEditorViewModel.Factory::class)
class AgentBindingEditorViewModel @AssistedInject constructor(
    @Assisted("agentType") private val agentType: String,
    @Assisted("isMemoryComponent") private val isMemoryComponent: Boolean,
    private val agentRepository: AgentRepository,
    private val settingsRepository: SettingsRepository,
    @ApplicationScope private val applicationScope: CoroutineScope,
) : ViewModel() {

    @AssistedFactory
    interface Factory {
        fun create(
            @Assisted("agentType") agentType: String,
            @Assisted("isMemoryComponent") isMemoryComponent: Boolean,
        ): AgentBindingEditorViewModel
    }

    private val _uiState = MutableStateFlow(EditorUiState(agentType = agentType, isDefault = agentType == "__default__"))
    val uiState: StateFlow<EditorUiState> = _uiState

    private val _events = MutableSharedFlow<EditorEvent>(extraBufferCapacity = 1)
    val events: SharedFlow<EditorEvent> = _events.asSharedFlow()

    private var putJob: Job? = null
    private var loadJob: Job? = null
    private var snapshot: EditorUiState? = null
    private var putPending: Boolean = false

    fun load() {
        if (loadJob?.isActive == true) return
        loadJob = viewModelScope.launch {
            val isDefault = agentType == "__default__"

            val accountsD = async { settingsRepository.getLlmAccounts() }
            val catalogD = async { settingsRepository.getLlmCatalog() }

            val bindingD = when {
                isDefault -> async { settingsRepository.getDefaultBinding() }
                isMemoryComponent -> async { agentRepository.getMemoryBinding(agentType) }
                else -> async { agentRepository.getAgentBinding(agentType) }
            }

            val accountsR = accountsD.await()
            val catalogR = catalogD.await()
            val bindingR = bindingD.await()

            val err = accountsR.exceptionOrNull() ?: catalogR.exceptionOrNull() ?: bindingR.exceptionOrNull()
            if (err != null) {
                _uiState.update { it.copy(loading = false, errorMessage = err.message) }
                return@launch
            }

            val accounts = accountsR.getOrThrow()
            val catalog = catalogR.getOrThrow()
            val binding: AgentBinding? = bindingR.getOrNull() as? AgentBinding

            val selectedAccountId = binding?.accountId
            val selectedAccount = accounts.firstOrNull { it.id == selectedAccountId }
            val models = if (selectedAccount != null) {
                resolveModelsForAccount(selectedAccount, catalog)
            } else {
                emptyList()
            }
            if (selectedAccount?.catalogProviderId == "custom" && models.isEmpty()) {
                _events.tryEmit(EditorEvent.Snackbar("Add a custom model before binding this account"))
            }
            val selectedModelOption = binding?.modelId?.let { mid ->
                models.firstOrNull { it.id == mid }
            }
            val capability = selectedModelOption?.thinkingCapability
            val effort = binding?.thinkingEffort.toThinkingEffort()
            val (coercedEffort, wasCoerced) = coerceEffort(effort, capability)

            _uiState.update {
                it.copy(
                    loading = false,
                    isDefault = isDefault,
                    accounts = accounts,
                    catalogProviders = catalog,
                    selectedAccount = selectedAccount,
                    availableModels = models,
                    selectedModel = selectedModelOption,
                    thinkingEffort = coercedEffort,
                    resolved = binding?.resolved,
                )
            }
            if (wasCoerced) schedulePut()
        }
    }

    fun selectAccount(accountId: String?) {
        val prev = _uiState.value
        val account = prev.accounts.firstOrNull { it.id == accountId }
        val accountChanged = prev.selectedAccount?.id != accountId
        val hadConfig = prev.thinkingEffort != ThinkingEffort.OFF

        // Apply selection synchronously; models will be resolved asynchronously.
        _uiState.update {
            it.copy(
                selectedAccount = account,
                availableModels = emptyList(),
                selectedModel = null,
                thinkingEffort = ThinkingEffort.OFF,
            )
        }
        if (accountChanged && hadConfig) {
            _events.tryEmit(EditorEvent.Snackbar("Thinking config reset for new account"))
        }

        viewModelScope.launch {
            if (account == null) return@launch
            val models = resolveModelsForAccount(account, prev.catalogProviders)
            // If user picked a different account while models were loading, discard stale result.
            if (_uiState.value.selectedAccount?.id != account.id) return@launch
            _uiState.update { it.copy(availableModels = models) }
            if (account.catalogProviderId == "custom" && models.isEmpty()) {
                _events.tryEmit(EditorEvent.Snackbar("Add a custom model before binding this account"))
            }
        }
    }

    fun selectModel(modelId: String) {
        val prev = _uiState.value
        val model = prev.availableModels.firstOrNull { it.id == modelId } ?: return
        val modelChanged = prev.selectedModel?.id != modelId

        val (coercedEffort, _) = if (modelChanged) {
            coerceEffort(ThinkingEffort.OFF, model.thinkingCapability)
        } else {
            Pair(prev.thinkingEffort, false)
        }

        _uiState.update {
            it.copy(
                selectedModel = model,
                thinkingEffort = coercedEffort,
            )
        }
        schedulePut()
    }

    fun clearBinding() {
        val s = _uiState.value
        if (s.isDefault) return
        _uiState.update {
            it.copy(
                selectedAccount = null,
                availableModels = emptyList(),
                selectedModel = null,
                thinkingEffort = ThinkingEffort.OFF,
            )
        }
        viewModelScope.launch {
            clearPersistedBinding(s)
        }
    }

    fun setEffort(e: ThinkingEffort) {
        _uiState.update { it.copy(thinkingEffort = e) }
        schedulePut()
    }

    private fun isPersistableSelection(s: EditorUiState): Boolean =
        s.selectedAccount != null && s.selectedModel != null

    private suspend fun persistBinding(s: EditorUiState): Result<AgentBinding> {
        val effort = s.thinkingEffort.toApiString()
        return when {
            s.isDefault -> settingsRepository.setDefaultBinding(
                s.selectedAccount?.id ?: return Result.failure(IllegalStateException("Default model requires an account")),
                s.selectedModel?.id ?: return Result.failure(IllegalStateException("Default model requires a model")),
                effort,
            )
            isMemoryComponent -> agentRepository.setMemoryBinding(
                s.agentType,
                s.selectedAccount?.id,
                s.selectedModel?.id,
                effort,
            )
            else -> agentRepository.setAgentBinding(
                s.agentType,
                s.selectedAccount?.id,
                s.selectedModel?.id,
                effort,
            )
        }
    }

    private suspend fun clearPersistedBinding(s: EditorUiState): Result<Unit> {
        return when {
            s.isDefault -> Result.failure(IllegalStateException("Default model cannot be cleared"))
            isMemoryComponent -> agentRepository.clearMemoryComponentBinding(s.agentType)
            else -> agentRepository.clearAgentBinding(s.agentType)
        }
    }

    private fun resolveCatalogModels(
        account: LlmAccount,
        catalog: List<CatalogProvider>,
    ): List<ModelOption> {
        val catalogProvider = catalog.firstOrNull { it.id == account.catalogProviderId } ?: return emptyList()
        return catalogProvider.models.map { m ->
            ModelOption(
                id = m.id,
                displayName = m.displayName,
                contextWindowTokens = m.contextWindowTokens,
                thinkingCapability = m.thinkingCapability,
            )
        }
    }

    private suspend fun resolveModelsForAccount(
        account: LlmAccount,
        catalog: List<CatalogProvider>,
    ): List<ModelOption> {
        if (account.catalogProviderId != "custom") {
            return resolveCatalogModels(account, catalog)
        }
        return settingsRepository.getCustomModels(account.id).getOrElse { emptyList() }.map { m ->
            ModelOption(
                id = m.modelId,
                displayName = m.displayName,
                contextWindowTokens = m.contextWindowTokens,
                thinkingCapability = m.thinkingCapability,
            )
        }
    }

    private fun schedulePut() {
        val s = _uiState.value

        if (s.isDefault && (s.selectedAccount == null || s.selectedModel == null)) {
            _uiState.update { it.copy(isSaving = false) }
            _events.tryEmit(EditorEvent.Snackbar("Default model requires an account and model"))
            return
        }

        if (!isPersistableSelection(s)) {
            putPending = false
            _uiState.update { it.copy(isSaving = false) }
            return
        }

        putJob?.cancel()
        snapshot = s
        putPending = true
        putJob = viewModelScope.launch {
            delay(300)
            val current = _uiState.value
            if (!isPersistableSelection(current) ||
                (current.isDefault && (current.selectedAccount == null || current.selectedModel == null))) {
                putPending = false
                _uiState.update { it.copy(isSaving = false) }
                return@launch
            }
            _uiState.update { it.copy(isSaving = true) }

            val r = persistBinding(current)
            putPending = false
            _uiState.update { it.copy(isSaving = false) }
            r.onFailure {
                val snap = snapshot
                if (snap != null) _uiState.value = snap.copy(errorMessage = null, isSaving = false)
                _events.tryEmit(EditorEvent.Snackbar("Failed to save. Retry?"))
            }
        }
    }

    override fun onCleared() {
        super.onCleared()
        if (putPending) {
            val s = _uiState.value
            if (!isPersistableSelection(s)) return
            applicationScope.launch {
                persistBinding(s)
            }
        }
    }

    private fun coerceEffort(
        effort: ThinkingEffort,
        capability: ThinkingCapability?,
    ): Pair<ThinkingEffort, Boolean> {
        val steps = capability?.let { effortStepsFor(it) } ?: return Pair(effort, false)
        if (steps.isEmpty()) return Pair(effort, false)
        if (effort !in steps) {
            val fallback = steps.lastOrNull { it != ThinkingEffort.OFF } ?: ThinkingEffort.OFF
            return Pair(fallback, true)
        }
        return Pair(effort, false)
    }
}
