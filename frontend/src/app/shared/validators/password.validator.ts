import { AbstractControl, ValidationErrors, ValidatorFn } from '@angular/forms';

export function passwordValidator(): ValidatorFn {
  return (control: AbstractControl): ValidationErrors | null => {
    const value = control.value as string;
    if (!value) return null;

    const errors: ValidationErrors = {};

    if (value.length < 8) errors['minLength'] = 'Password must be at least 8 characters';
    if (!/[A-Z]/.test(value)) errors['uppercase'] = 'Must contain an uppercase letter';
    if (!/[a-z]/.test(value)) errors['lowercase'] = 'Must contain a lowercase letter';
    if (!/\d/.test(value)) errors['digit'] = 'Must contain a digit';

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
