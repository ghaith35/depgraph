mod foo;

use crate::foo::bar::helper;
use crate::foo::utils;

fn main() {
    helper();
    utils::run();
}
