import { createReducer, on } from '@ngrx/store';
import { UserResponse } from '../../models/user.model';
import { AuthActions } from './auth.actions';

export interface AuthState {
  user: UserResponse | null;
  token: string | null;
  loading: boolean;
  error: string | null;
  isAuthenticated: boolean;
  userLoaded: boolean;
}

export const initialState: AuthState = {
  user: null,
  token: null,
  loading: false,
  error: null,
  isAuthenticated: false,
  userLoaded: false,
};

export const authReducer = createReducer(
  initialState,
  on(AuthActions.login, (state) => ({
    ...state,
    loading: true,
    error: null,
  })),
  on(AuthActions.loginSuccess, (state, { token }) => ({
    ...state,
    token,
    loading: false,
    isAuthenticated: true,
    error: null,
  })),
  on(AuthActions.loginFailure, (state, { error }) => ({
    ...state,
    loading: false,
    error,
    isAuthenticated: false,
  })),
  on(AuthActions.loadUserSuccess, (state, { user }) => ({
    ...state,
    user,
    userLoaded: true,
  })),
  on(AuthActions.loadUserFailure, (state, { error }) => ({
    ...state,
    error,
    userLoaded: true,
  })),
  on(AuthActions.logoutComplete, AuthActions.sessionExpired, () => ({
    ...initialState,
  }))
);
