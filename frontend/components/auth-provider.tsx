"use client";

import {
  type Auth,
  browserSessionPersistence,
  createUserWithEmailAndPassword,
  fetchSignInMethodsForEmail,
  onAuthStateChanged,
  sendPasswordResetEmail,
  setPersistence,
  signInWithEmailAndPassword,
  signOut,
  type User,
} from "firebase/auth";
import { createContext, useContext, useEffect, useMemo, useState } from "react";

import { getFirebaseAuthClient, isFirebaseConfigured } from "@/lib/firebase-client";

type AuthState = {
  user: User | null;
  token: string | null;
  loading: boolean;
  error: string | null;
  signInWithEmailPassword: (email: string, password: string) => Promise<string>;
  createUserWithEmailPassword: (email: string, password: string) => Promise<string>;
  sendResetForEmail: (email: string) => Promise<void>;
  hasPasswordSignIn: (email: string) => Promise<boolean>;
  signOutUser: () => Promise<void>;
  refreshToken: () => Promise<string | null>;
};

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  const firebaseConfigured = isFirebaseConfigured();
  const [auth] = useState<Auth | null>(() => (firebaseConfigured ? getFirebaseAuthClient() : null));
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(auth));
  const initialError = !firebaseConfigured || !auth ? "Authentication service is unavailable." : null;
  const [error, setError] = useState<string | null>(initialError);

  useEffect(() => {
    if (!auth) {
      return;
    }

    const init = async () => {
      await setPersistence(auth, browserSessionPersistence);
      return onAuthStateChanged(auth, async (nextUser) => {
        setUser(nextUser);
        setLoading(false);
        if (!nextUser) {
          setToken(null);
          return;
        }
        const idToken = await nextUser.getIdToken(true);
        setToken(idToken);
      });
    };

    let unsubscribe: (() => void) | undefined;
    init()
      .then((cleanup) => {
        unsubscribe = cleanup;
      })
      .catch(() => {
        setError("Authentication service is unavailable.");
        setLoading(false);
      });

    return () => {
      if (unsubscribe) {
        unsubscribe();
      }
    };
  }, [auth]);

  const value = useMemo<AuthState>(
    () => ({
      user,
      token,
      loading,
      error,
      signInWithEmailPassword: async (email: string, password: string) => {
        if (!auth) {
          throw new Error("Authentication service is unavailable.");
        }
        setError(null);
        const credential = await signInWithEmailAndPassword(auth, email, password);
        const idToken = await credential.user.getIdToken(true);
        setUser(credential.user);
        setToken(idToken);
        return idToken;
      },
      createUserWithEmailPassword: async (email: string, password: string) => {
        if (!auth) {
          throw new Error("Authentication service is unavailable.");
        }
        setError(null);
        const credential = await createUserWithEmailAndPassword(auth, email, password);
        const idToken = await credential.user.getIdToken(true);
        setUser(credential.user);
        setToken(idToken);
        return idToken;
      },
      sendResetForEmail: async (email: string) => {
        if (!auth) {
          throw new Error("Authentication service is unavailable.");
        }
        setError(null);
        await sendPasswordResetEmail(auth, email);
      },
      hasPasswordSignIn: async (email: string) => {
        if (!auth) {
          return false;
        }
        const providers = await fetchSignInMethodsForEmail(auth, email);
        return providers.includes("password");
      },
      signOutUser: async () => {
        if (!auth) {
          return;
        }
        setError(null);
        await signOut(auth);
        setUser(null);
        setToken(null);
      },
      refreshToken: async () => {
        if (!auth) {
          return null;
        }
        if (!auth.currentUser) {
          setToken(null);
          return null;
        }
        const refreshed = await auth.currentUser.getIdToken(true);
        setToken(refreshed);
        return refreshed;
      },
    }),
    [auth, error, loading, token, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}