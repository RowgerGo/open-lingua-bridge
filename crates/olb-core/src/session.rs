use olb_protocol::ErrorCode;
use uuid::Uuid;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SessionState {
    Idle,
    Starting,
    Running,
    Paused,
    Stopped,
    Error,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SessionEvent {
    StartRequested,
    BackendReady,
    PauseRequested,
    ResumeRequested,
    StopRequested,
    ResetRequested,
}

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum SessionError {
    #[error("session state {from:?} cannot handle event {event:?}")]
    InvalidTransition { from: SessionState, event: SessionEvent },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SessionManager {
    state: SessionState,
    current_session_id: Option<String>,
    last_error: Option<ErrorCode>,
}

pub type SessionStateMachine = SessionManager;

impl Default for SessionManager {
    fn default() -> Self {
        Self {
            state: SessionState::Idle,
            current_session_id: None,
            last_error: None,
        }
    }
}

impl SessionManager {
    pub fn state(&self) -> SessionState {
        self.state
    }

    pub fn current_session_id(&self) -> Option<&str> {
        self.current_session_id.as_deref()
    }

    pub fn last_error(&self) -> Option<ErrorCode> {
        self.last_error
    }

    pub fn start(&mut self) -> Result<&str, SessionError> {
        self.apply(SessionEvent::StartRequested)?;
        Ok(self.current_session_id.as_deref().expect("start creates session id"))
    }

    pub fn mark_running(&mut self) -> Result<(), SessionError> {
        self.apply(SessionEvent::BackendReady)
    }

    pub fn pause(&mut self) -> Result<(), SessionError> {
        self.apply(SessionEvent::PauseRequested)
    }

    pub fn resume(&mut self) -> Result<(), SessionError> {
        self.apply(SessionEvent::ResumeRequested)
    }

    pub fn stop(&mut self) -> Result<(), SessionError> {
        self.apply(SessionEvent::StopRequested)
    }

    pub fn reset(&mut self) -> Result<(), SessionError> {
        self.apply(SessionEvent::ResetRequested)
    }

    pub fn fail(&mut self, error: ErrorCode) {
        self.state = SessionState::Error;
        self.current_session_id = None;
        self.last_error = Some(error);
    }

    pub fn apply(&mut self, event: SessionEvent) -> Result<(), SessionError> {
        let next_state = match (self.state, event) {
            (SessionState::Idle | SessionState::Stopped, SessionEvent::StartRequested) => {
                self.current_session_id = Some(format!("ses_{}", Uuid::new_v4().simple()));
                self.last_error = None;
                SessionState::Starting
            }
            (SessionState::Starting, SessionEvent::BackendReady) => SessionState::Running,
            (SessionState::Running, SessionEvent::PauseRequested) => SessionState::Paused,
            (SessionState::Paused, SessionEvent::ResumeRequested) => SessionState::Running,
            (SessionState::Starting | SessionState::Running | SessionState::Paused, SessionEvent::StopRequested) => {
                self.current_session_id = None;
                SessionState::Stopped
            }
            (SessionState::Error | SessionState::Stopped, SessionEvent::ResetRequested) => {
                self.current_session_id = None;
                self.last_error = None;
                SessionState::Idle
            }
            (from, event) => return Err(SessionError::InvalidTransition { from, event }),
        };
        self.state = next_state;
        Ok(())
    }

    pub fn transition(&mut self, to: SessionState) -> Result<(), SessionError> {
        match to {
            SessionState::Starting => self.apply(SessionEvent::StartRequested),
            SessionState::Running if self.state == SessionState::Starting => self.apply(SessionEvent::BackendReady),
            SessionState::Running => self.apply(SessionEvent::ResumeRequested),
            SessionState::Paused => self.apply(SessionEvent::PauseRequested),
            SessionState::Stopped => self.apply(SessionEvent::StopRequested),
            SessionState::Idle => self.apply(SessionEvent::ResetRequested),
            SessionState::Error => {
                self.fail(ErrorCode::InternalError);
                Ok(())
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn supports_p1_lifecycle() {
        let mut sm = SessionStateMachine::default();
        sm.transition(SessionState::Starting).unwrap();
        sm.transition(SessionState::Running).unwrap();
        sm.transition(SessionState::Paused).unwrap();
        sm.transition(SessionState::Running).unwrap();
        sm.transition(SessionState::Stopped).unwrap();
        assert_eq!(sm.state(), SessionState::Stopped);
    }

    #[test]
    fn rejects_invalid_pause_from_idle() {
        let mut sm = SessionStateMachine::default();
        assert_eq!(sm.pause().unwrap_err(), SessionError::InvalidTransition { from: SessionState::Idle, event: SessionEvent::PauseRequested });
    }

    #[test]
    fn records_error_and_resets() {
        let mut sm = SessionManager::default();
        sm.start().unwrap();
        sm.fail(ErrorCode::BackendUnreachable);
        assert_eq!(sm.state(), SessionState::Error);
        assert_eq!(sm.current_session_id(), None);
        assert_eq!(sm.last_error(), Some(ErrorCode::BackendUnreachable));
        sm.reset().unwrap();
        assert_eq!(sm.state(), SessionState::Idle);
        assert_eq!(sm.last_error(), None);
    }
}
