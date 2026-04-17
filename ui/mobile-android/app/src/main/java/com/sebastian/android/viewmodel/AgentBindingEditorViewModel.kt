package com.sebastian.android.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.sebastian.android.data.model.Provider
import com.sebastian.android.data.model.ThinkingCapability
import com.sebastian.android.data.model.ThinkingEffort
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
    val providers: List<Provider> = emptyList(),
    val selectedProvider: Provider? = null,
    val thinkingEffort: ThinkingEffort = ThinkingEffort.OFF,
    val isSaving: Boolean = false,
    val errorMessage: String? = null,
    val loading: Boolean = true,
) {
    val effectiveCapability: ThinkingCapability?
        get() = (selectedProvider ?: providers.firstOrNull { it.isDefault })?.thinkingCapability
}

sealed interface EditorEvent {
    data class Snackbar(val text: String) : EditorEvent
}

@HiltViewModel(assistedFactory = AgentBindingEditorViewModel.Factory::class)
class AgentBindingEditorViewModel @AssistedInject constructor(
    @Assisted private val agentType: String,
    private val agentRepository: AgentRepository,
    private val settingsRepository: SettingsRepository,
    @ApplicationScope private val applicationScope: CoroutineScope,
) : ViewModel() {

    @AssistedFactory
    interface Factory {
        fun create(agentType: String): AgentBindingEditorViewModel
    }

    private val _uiState = MutableStateFlow(EditorUiState(agentType = agentType))
    val uiState: StateFlow<EditorUiState> = _uiState

    private val _events = MutableSharedFlow<EditorEvent>(extraBufferCapacity = 1)
    val events: SharedFlow<EditorEvent> = _events.asSharedFlow()

    private var putJob: Job? = null
    private var loadJob: Job? = null
    private var snapshot: EditorUiState? = null

    // 仅在 debounce 已排队但 setBinding 调用尚未返回时为 true。
    // onCleared 用它判断是否需要在 viewModelScope 已取消后补发末次写入。
    private var putPending: Boolean = false

    fun load() {
        // 幂等：旋转/重组 重复触发时，正在进行的 load 不再重复拉；避免覆盖用户刚改的选择
        if (loadJob?.isActive == true) return
        loadJob = viewModelScope.launch {
            val bindingR = agentRepository.getBinding(agentType)
            val providersR = settingsRepository.getProviders()
            val err = bindingR.exceptionOrNull() ?: providersR.exceptionOrNull()
            if (err != null) {
                _uiState.update { it.copy(loading = false, errorMessage = err.message) }
                return@launch
            }
            val dto = bindingR.getOrThrow()
            val providers = providersR.getOrThrow()
            val selected = providers.firstOrNull { it.id == dto.providerId }
            val capability = (selected ?: providers.firstOrNull { it.isDefault })?.thinkingCapability
            val (coercedEffort, wasCoerced) =
                coerceEffort(dto.thinkingEffort.toThinkingEffort(), capability)
            _uiState.update {
                it.copy(
                    loading = false,
                    providers = providers,
                    selectedProvider = selected,
                    thinkingEffort = coercedEffort,
                )
            }
            if (wasCoerced) schedulePut()
        }
    }

    fun selectProvider(providerId: String?) {
        val prev = _uiState.value
        val next = prev.providers.firstOrNull { it.id == providerId }
        val providerChanged = prev.selectedProvider?.id != providerId
        val hadConfig = prev.thinkingEffort != ThinkingEffort.OFF
        _uiState.update {
            it.copy(
                selectedProvider = next,
                thinkingEffort = if (providerChanged) ThinkingEffort.OFF else it.thinkingEffort,
            )
        }
        if (providerChanged && hadConfig) {
            _events.tryEmit(EditorEvent.Snackbar("Thinking config reset for new provider"))
        }
        schedulePut()
    }

    fun setEffort(e: ThinkingEffort) {
        _uiState.update { it.copy(thinkingEffort = e) }
        schedulePut()
    }

    private fun schedulePut() {
        putJob?.cancel()
        snapshot = _uiState.value
        putPending = true
        putJob = viewModelScope.launch {
            delay(300)
            val s = _uiState.value
            _uiState.update { it.copy(isSaving = true) }
            val r = agentRepository.setBinding(
                agentType,
                s.selectedProvider?.id,
                s.thinkingEffort,
            )
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
        // ViewModel.clear() 先取消 viewModelScope 再调用 onCleared，所以此时 putJob 已死。
        // 用 putPending 判断 debounce 窗口内的末次写入是否还没真正发出去，
        // 切到进程存活期的 applicationScope 补发。
        if (putPending) {
            val s = _uiState.value
            applicationScope.launch {
                agentRepository.setBinding(agentType, s.selectedProvider?.id, s.thinkingEffort)
            }
        }
    }

    private fun coerceEffort(
        effort: ThinkingEffort,
        capability: ThinkingCapability?,
    ): Pair<ThinkingEffort, Boolean> {
        val steps = capability?.let { effortStepsFor(it) } ?: return Pair(effort, false)
        // NONE / ALWAYS_ON 无档位可选，保持传入值不触发 PUT
        if (steps.isEmpty()) return Pair(effort, false)
        if (effort !in steps) {
            // 钳到最高合法档位
            val fallback = steps.lastOrNull { it != ThinkingEffort.OFF } ?: ThinkingEffort.OFF
            return Pair(fallback, true)
        }
        return Pair(effort, false)
    }
}
