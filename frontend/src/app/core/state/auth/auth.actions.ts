import { createActionGroup, emptyProps, props } from '@ngrx/store';
import { LoginRequest, UserResponse } from '../../models/user.model';

export const AuthActions = createActionGroup({
  source: 'Auth',
  events: {
    Login: props<{ request: LoginRequest }>(),
    'Login Success': props<{ expiresIn: number }>(),
    'Login Failure': props<{ error: string }>(),
    'Load User': emptyProps(),
    'Load User Success': props<{ user: UserResponse }>(),
    'Load User Failure': props<{ error: string }>(),
    Logout: emptyProps(),
    'Logout Complete': emptyProps(),
    'Session Expired': emptyProps(),
  },
});
