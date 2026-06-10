public class Greeter {
    private final String name;
    private final String greeting;

    public Greeter(String name) {
        this.name = name;
        this.greeting = "Hi";
    }

    public String greet() {
        return greeting + ", " + name;
    }
}
