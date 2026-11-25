package com.xiongbot.ecgrecords;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import org.json.JSONObject;

/** Opt-in credentials encrypted with a non-exportable Android Keystore key. */
final class CredentialStore {
    private static final String ALIAS="ecg-health-login-v1";
    private final SharedPreferences preferences;
    CredentialStore(Context context){preferences=context.getSharedPreferences("health-login",Context.MODE_PRIVATE);}
    private SecretKey key() throws Exception {
        KeyStore store=KeyStore.getInstance("AndroidKeyStore");store.load(null);
        if(store.containsAlias(ALIAS))return (SecretKey)store.getKey(ALIAS,null);
        KeyGenerator generator=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(ALIAS,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true).setKeySize(256).build());
        return generator.generateKey();
    }
    void save(String username,String password) throws Exception {
        if(!username.matches("[a-z0-9][a-z0-9_-]{2,31}")||password.codePointCount(0,password.length())<5||password.codePointCount(0,password.length())>128)
            throw new IllegalArgumentException("Invalid credentials");
        JSONObject payload=new JSONObject().put("username",username).put("password",password);
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key());
        cipher.updateAAD(WebPolicy.ORIGIN.getBytes(StandardCharsets.UTF_8));
        String encrypted=Base64.encodeToString(cipher.doFinal(payload.toString().getBytes(StandardCharsets.UTF_8)),Base64.NO_WRAP);
        String iv=Base64.encodeToString(cipher.getIV(),Base64.NO_WRAP);
        if(!preferences.edit().putString("ciphertext",encrypted).putString("iv",iv).commit())throw new IllegalStateException("Unable to save credentials");
    }
    JSONObject load() throws Exception {
        String encrypted=preferences.getString("ciphertext",null),iv=preferences.getString("iv",null);
        if(encrypted==null||iv==null)return null;
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,Base64.decode(iv,Base64.NO_WRAP)));
        cipher.updateAAD(WebPolicy.ORIGIN.getBytes(StandardCharsets.UTF_8));
        return new JSONObject(new String(cipher.doFinal(Base64.decode(encrypted,Base64.NO_WRAP)),StandardCharsets.UTF_8));
    }
    void clear() throws Exception {
        if(!preferences.edit().clear().commit())throw new IllegalStateException("Unable to clear credentials");
        KeyStore store=KeyStore.getInstance("AndroidKeyStore");store.load(null);if(store.containsAlias(ALIAS))store.deleteEntry(ALIAS);
    }
}
