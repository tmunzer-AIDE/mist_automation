import { AbstractControl, ValidationErrors, ValidatorFn } from '@angular/forms';
import { PasswordPolicy } from '../../core/models/session.model';

const DEFAULT_POLICY: PasswordPolicy = {
  min_length: 8,
  require_uppercase: true,
  require_lowercase: true,
  require_digits: true,
  require_special_chars: false,
};

export function passwordValidator(policy?: PasswordPolicy): ValidatorFn {
  const p = policy ?? DEFAULT_POLICY;

  return (control: AbstractControl): ValidationErrors | null => {
    const value = control.value as string;
    if (!value) return null;

    const errors: ValidationErrors = {};

    if (value.length < p.min_length)
      errors['minLength'] = `Password must be at least ${p.min_length} characters`;
    if (p.require_uppercase && !/[A-Z]/.test(value))
      errors['uppercase'] = 'Must contain an uppercase letter';
    if (p.require_lowercase && !/[a-z]/.test(value))
      errors['lowercase'] = 'Must contain a lowercase letter';
    if (p.require_digits && !/\d/.test(value)) errors['digit'] = 'Must contain a digit';
    if (p.require_special_chars && !/[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?`~]/.test(value))
      errors['special'] = 'Must contain a special character';

    return Object.keys(errors).length ? errors : null;
  };
}

export function matchPasswordValidator(passwordField: string): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    const password = control.parent?.get(passwordField)?.value;
    if (control.value !== password) {
      return { passwordMismatch: true };
    }
    return null;
  };
}
