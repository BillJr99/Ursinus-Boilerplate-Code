/*
 * code-viz Java tracer (JdiTrace.java): run a compiled Java program under the Java debugger (JDI) and
 * record, at every line of the example's own classes, the call stack with each frame's local
 * variables and the objects they reach, in the same trace format as the Python view ("env"), so the
 * viewer draws Java frames and objects with arrows the way it draws Python's.
 *
 * Full manual: the header of code-viz (`code-viz readme`, or README.md), sections 7 Kinds of
 * visualization (java) and 14 Trace format. Called by langrun.py inside the java runner container,
 * which compiles this file once per container (javac -d /tmp/cviz-jdi JdiTrace.java).
 *
 * USAGE  java -cp /tmp/cviz-jdi JdiTrace CLASSPATH MAINCLASS MAXSTEPS USERCLASSES
 *        USERCLASSES: comma-separated names of the example's own classes (only their lines are stepped).
 *        Prints one JSON trace on stdout:
 *        {"version":1,"kind":"env","language":"java","steps":[{"event":"line","line":N,"out":chars,
 *          "stack":[{"func":"main","line":N,"vars":{name: value}}],"heap":{"id":object}}],
 *         "stdout":"...","error":null|"...","truncated":bool}
 *        Values: {"p": number or string} (numbers and Strings), {"x": "true"|"false"|"null"|"'c'"}
 *        (literals shown as they are), {"r": "id"} (a reference to heap[id]). Objects: arrays
 *        {"t":"array","class":"int[]","items":[...],"more":n}, java.util.ArrayList as
 *        {"t":"list","class":"ArrayList",...}, the example's own objects {"t":"instance","class":"Name",
 *        "attrs":{field: value}}, anything else {"t": its simple class name, "repr": "Type (size N)"}.
 *
 * HOW IT WORKS  It launches the program suspended (LaunchingConnector), sets a breakpoint on main once
 * the main class loads, then single-steps lines (STEP_INTO) with java.*, javax.*, jdk.*, sun.* and
 * com.sun.* excluded, so library code runs without being stepped. At each step it drains the
 * program's output so far (System.out flushes on println) to record how much was printed.
 *
 * LIMITS  At most MAXSTEPS lines (then the program gets three more seconds to finish, unrecorded),
 * 60 objects per step, 30 items per array or list. Boxed numbers are shown as their value. Threads
 * other than main are not stepped. Standard input is not connected.
 */
import com.sun.jdi.*;
import com.sun.jdi.connect.*;
import com.sun.jdi.event.*;
import com.sun.jdi.request.*;

import java.io.*;
import java.util.*;

public class JdiTrace {
    static final StringBuilder OUT = new StringBuilder();
    static final StringBuilder ERR = new StringBuilder();
    static InputStream pout, perr;
    static Set<String> users;
    static final int MAX_OBJECTS = 60, MAX_ITEMS = 30;
    static final Set<String> BOXED = new HashSet<>(Arrays.asList("java.lang.Integer", "java.lang.Long",
            "java.lang.Short", "java.lang.Byte", "java.lang.Double", "java.lang.Float", "java.lang.Boolean",
            "java.lang.Character"));

    public static void main(String[] a) throws Exception {
        String cp = a[0], mainClass = a[1];
        int max = Integer.parseInt(a[2]);
        users = new HashSet<>(Arrays.asList(a[3].split(",")));
        LaunchingConnector lc = Bootstrap.virtualMachineManager().defaultConnector();
        Map<String, Connector.Argument> args = lc.defaultArguments();
        args.get("main").setValue(mainClass);
        args.get("options").setValue("-cp " + cp + " -Xmx256m");
        VirtualMachine vm = lc.launch(args);
        Process p = vm.process();
        pout = p.getInputStream();
        perr = p.getErrorStream();
        p.getOutputStream().close();
        EventRequestManager erm = vm.eventRequestManager();
        ClassPrepareRequest cpr = erm.createClassPrepareRequest();
        cpr.addClassFilter(mainClass);
        cpr.enable();
        List<Object> steps = new ArrayList<>();
        boolean truncated = false, done = false;
        String error = null;
        StepRequest sr = null;
        EventQueue q = vm.eventQueue();
        while (!done) {
            EventSet es = q.remove();
            for (Event e : es) {
                if (e instanceof ClassPrepareEvent) {
                    for (Method m : ((ClassPrepareEvent) e).referenceType().methodsByName("main")) {
                        if (m.isStatic() && m.location() != null) erm.createBreakpointRequest(m.location()).enable();
                    }
                } else if (e instanceof BreakpointEvent) {
                    ThreadReference th = ((BreakpointEvent) e).thread();
                    erm.deleteEventRequests(new ArrayList<>(erm.breakpointRequests()));
                    sr = erm.createStepRequest(th, StepRequest.STEP_LINE, StepRequest.STEP_INTO);
                    for (String ex : new String[]{"java.*", "javax.*", "jdk.*", "sun.*", "com.sun.*"}) sr.addClassExclusionFilter(ex);
                    sr.enable();
                    steps.add(record((LocatableEvent) e));
                } else if (e instanceof StepEvent) {
                    if (!users.contains(((StepEvent) e).location().declaringType().name())) continue;
                    if (steps.size() >= max) {
                        truncated = true;
                        erm.deleteEventRequest(sr);
                        final VirtualMachine v = vm;
                        Thread t = new Thread(() -> { try { Thread.sleep(3000); v.exit(0); } catch (Exception ignored) { } });
                        t.setDaemon(true);
                        t.start();
                    } else {
                        steps.add(record((LocatableEvent) e));
                    }
                } else if (e instanceof VMDeathEvent || e instanceof VMDisconnectEvent) {
                    done = true;
                }
            }
            if (!done) es.resume();
        }
        int code = p.waitFor();
        drain();
        drainAll(pout, OUT);
        drainAll(perr, ERR);
        if (code != 0 && !truncated) error = "exit " + code;
        Map<String, Object> t = new LinkedHashMap<>();
        t.put("version", 1);
        t.put("kind", "env");
        t.put("language", "java");
        t.put("steps", steps);
        t.put("stdout", OUT.toString() + (code != 0 ? ERR.toString() : ""));
        t.put("error", error);
        t.put("truncated", truncated);
        System.out.print(json(t));
    }

    static void drain() {
        try {
            byte[] b = new byte[8192];
            while (pout.available() > 0) { int n = pout.read(b); if (n <= 0) break; OUT.append(new String(b, 0, n, "UTF-8")); }
            while (perr.available() > 0) { int n = perr.read(b); if (n <= 0) break; ERR.append(new String(b, 0, n, "UTF-8")); }
        } catch (IOException ignored) { }
    }

    static void drainAll(InputStream in, StringBuilder sb) {
        try {
            byte[] b = new byte[8192];
            int n;
            while ((n = in.read(b)) > 0) sb.append(new String(b, 0, n, "UTF-8"));
        } catch (IOException ignored) { }
    }

    static Map<String, Object> record(LocatableEvent ev) {
        drain();
        Map<String, Object> s = new LinkedHashMap<>();
        Map<String, Object> heap = new LinkedHashMap<>();
        s.put("event", "line");
        s.put("line", ev.location().lineNumber());
        List<Object> stack = new ArrayList<>();
        try {
            List<StackFrame> frames = new ArrayList<>(ev.thread().frames());
            Collections.reverse(frames);
            for (StackFrame f : frames) {
                Location loc = f.location();
                if (!users.contains(loc.declaringType().name())) continue;
                Map<String, Object> fr = new LinkedHashMap<>();
                Method m = loc.method();
                fr.put("func", m.isConstructor() ? "new " + simple(loc.declaringType().name()) : m.name());
                fr.put("line", loc.lineNumber());
                Map<String, Object> vars = new LinkedHashMap<>();
                ObjectReference self = f.thisObject();
                if (self != null) vars.put("this", enc(self, heap));
                try {
                    for (LocalVariable lv : f.visibleVariables()) vars.put(lv.name(), enc(f.getValue(lv), heap));
                } catch (AbsentInformationException ignored) { }
                fr.put("vars", vars);
                stack.add(fr);
            }
        } catch (IncompatibleThreadStateException ignored) { }
        s.put("stack", stack);
        s.put("heap", heap);
        s.put("out", OUT.length());
        return s;
    }

    static String simple(String n) { int i = n.lastIndexOf('.'); return i < 0 ? n : n.substring(i + 1); }

    static Map<String, Object> lit(String k, Object v) { Map<String, Object> m = new LinkedHashMap<>(); m.put(k, v); return m; }

    static Object enc(Value v, Map<String, Object> heap) {
        if (v == null) return lit("x", "null");
        if (v instanceof BooleanValue) return lit("x", String.valueOf(((BooleanValue) v).value()));
        if (v instanceof CharValue) return lit("x", "'" + ((CharValue) v).value() + "'");
        if (v instanceof DoubleValue || v instanceof FloatValue) {
            double d = ((PrimitiveValue) v).doubleValue();
            return Double.isFinite(d) ? lit("p", d) : lit("x", String.valueOf(d));
        }
        if (v instanceof PrimitiveValue) return lit("p", ((PrimitiveValue) v).longValue());
        if (v instanceof StringReference) return lit("p", ((StringReference) v).value());
        ObjectReference o = (ObjectReference) v;
        String type = o.referenceType().name();
        if (BOXED.contains(type)) {
            Field f = o.referenceType().fieldByName("value");
            if (f != null) return enc(o.getValue(f), heap);
        }
        String id = String.valueOf(o.uniqueID());
        if (!heap.containsKey(id) && heap.size() < MAX_OBJECTS) {
            Map<String, Object> obj = new LinkedHashMap<>();
            heap.put(id, obj);
            if (o instanceof ArrayReference) {
                ArrayReference ar = (ArrayReference) o;
                int n = ar.length();
                obj.put("t", "array");
                obj.put("class", simple(type));
                List<Object> items = new ArrayList<>();
                for (Value x : ar.getValues(0, Math.min(n, MAX_ITEMS))) items.add(enc(x, heap));
                obj.put("items", items);
                if (n > MAX_ITEMS) obj.put("more", n - MAX_ITEMS);
            } else if (type.equals("java.util.ArrayList")) {
                Field data = o.referenceType().fieldByName("elementData"), size = o.referenceType().fieldByName("size");
                int n = size != null ? ((IntegerValue) o.getValue(size)).value() : 0;
                obj.put("t", "list");
                obj.put("class", "ArrayList");
                List<Object> items = new ArrayList<>();
                Value d = data != null ? o.getValue(data) : null;
                if (d instanceof ArrayReference)
                    for (Value x : ((ArrayReference) d).getValues(0, Math.min(n, MAX_ITEMS))) items.add(enc(x, heap));
                obj.put("items", items);
                if (n > MAX_ITEMS) obj.put("more", n - MAX_ITEMS);
            } else if (users.contains(type)) {
                obj.put("t", "instance");
                obj.put("class", simple(type));
                Map<String, Object> attrs = new LinkedHashMap<>();
                for (Field f : o.referenceType().allFields()) if (!f.isStatic()) attrs.put(f.name(), enc(o.getValue(f), heap));
                obj.put("attrs", attrs);
            } else {
                obj.put("t", simple(type));
                Field size = o.referenceType().fieldByName("size");
                String repr = simple(type);
                if (size != null && o.getValue(size) instanceof IntegerValue) repr += " (size " + ((IntegerValue) o.getValue(size)).value() + ")";
                obj.put("repr", repr);
            }
        }
        return lit("r", id);
    }

    static String json(Object o) {
        StringBuilder b = new StringBuilder();
        write(b, o);
        return b.toString();
    }

    @SuppressWarnings("unchecked")
    static void write(StringBuilder b, Object o) {
        if (o == null) { b.append("null"); return; }
        if (o instanceof String) { str(b, (String) o); return; }
        if (o instanceof Number || o instanceof Boolean) { b.append(o); return; }
        if (o instanceof Map) {
            b.append('{');
            boolean first = true;
            for (Map.Entry<String, Object> e : ((Map<String, Object>) o).entrySet()) {
                if (!first) b.append(',');
                first = false;
                str(b, e.getKey());
                b.append(':');
                write(b, e.getValue());
            }
            b.append('}');
            return;
        }
        if (o instanceof List) {
            b.append('[');
            boolean first = true;
            for (Object x : (List<Object>) o) { if (!first) b.append(','); first = false; write(b, x); }
            b.append(']');
            return;
        }
        str(b, o.toString());
    }

    static void str(StringBuilder b, String s) {
        b.append('"');
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"': b.append("\\\""); break;
                case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n"); break;
                case '\r': b.append("\\r"); break;
                case '\t': b.append("\\t"); break;
                default:
                    if (c < 0x20) b.append(String.format("\\u%04x", (int) c)); else b.append(c);
            }
        }
        b.append('"');
    }
}
