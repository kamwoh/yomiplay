// Shared page state: set once the server has been told to quit, so no socket tries to reconnect.
export const page = { stopped: false };
